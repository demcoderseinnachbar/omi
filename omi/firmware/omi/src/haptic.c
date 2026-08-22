#include "lib/core/haptic.h"

#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/spinlock.h>

LOG_MODULE_REGISTER(haptic, CONFIG_LOG_DEFAULT_LEVEL);

#define MAX_HAPTIC_DURATION 5000

static const struct gpio_dt_spec haptic_pin = GPIO_DT_SPEC_GET_OR(DT_NODELABEL(motor_pin), gpios, {0});

// Haptic Off Work Item
static struct k_work_delayable haptic_off_work;

// Guards the pair (haptic_off_at, motor pin). Held across a tick read, a
// comparison and one GPIO register write and never across a blocking call, so
// it is safe to take from any thread -- including the system workqueue that
// runs haptic_off_work itself, which turnoff_all() does.
static struct k_spinlock haptic_lock;

// Tick at which the pulse that currently owns the motor is due to end. A work
// handler may only switch the motor off once this has been reached. An older
// handler that was still running when a newer pulse started finds a deadline in
// the future and leaves the motor alone; the newer pulse has already moved the
// off item to its own deadline.
static int64_t haptic_off_at;

// Work handler to turn off haptic motor
static void haptic_off_work_handler(struct k_work *work)
{
    k_spinlock_key_t key = k_spin_lock(&haptic_lock);
    bool expired = k_uptime_ticks() >= haptic_off_at;

    if (expired) {
        haptic_off();
    }

    k_spin_unlock(&haptic_lock, key);

    // Logging stays outside the lock: the backend may defer, and nothing that
    // can block belongs in a spinlock section.
    if (expired) {
        LOG_INF("Haptic turned off by work handler");
    } else {
        LOG_DBG("Stale haptic off ignored, a newer pulse owns the motor");
    }
}

// The capture alarm's own delayable item, declared here because haptic_init()
// below arms it. Everything it does lives at the bottom of this file.
static struct k_work_delayable alarm_work;
static void alarm_work_handler(struct k_work *work);

// BLE Service definitions
static void haptic_ccc_cfg_changed(const struct bt_gatt_attr *attr, uint16_t value);
static ssize_t haptic_write_handler(struct bt_conn *conn,
                                    const struct bt_gatt_attr *attr,
                                    const void *buf,
                                    uint16_t len,
                                    uint16_t offset,
                                    uint8_t flags);

// Define a unique UUID for the Haptic Service
static struct bt_uuid_128 haptic_service_uuid =
    BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xCAB1AB95, 0x2EA5, 0x4F4D, 0xBB56, 0x874B72CFC984));
static struct bt_uuid_128 haptic_char_uuid =
    BT_UUID_INIT_128(BT_UUID_128_ENCODE(0xCAB1AB96, 0x2EA5, 0x4F4D, 0xBB56, 0x874B72CFC984));

// Define the Haptic GATT Service structure
static struct bt_gatt_attr haptic_attrs[] = {
    BT_GATT_PRIMARY_SERVICE(&haptic_service_uuid),
    BT_GATT_CHARACTERISTIC(&haptic_char_uuid.uuid,
                           BT_GATT_CHRC_WRITE,
                           BT_GATT_PERM_WRITE,
                           NULL,
                           haptic_write_handler,
                           NULL),
};

static struct bt_gatt_service haptic_service = BT_GATT_SERVICE(haptic_attrs);

// Haptic Write Handler
static ssize_t haptic_write_handler(struct bt_conn *conn,
                                    const struct bt_gatt_attr *attr,
                                    const void *buf,
                                    uint16_t len,
                                    uint16_t offset,
                                    uint8_t flags)
{
    if (len < 1) {
        LOG_WRN("Haptic write: Invalid length %d", len);
        return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
    }

    uint8_t value = ((uint8_t *) buf)[0];
    LOG_INF("Haptic write received: value %d", value);

    // Map received value to haptic duration
    // 1 -> 100ms, 2 -> 300ms, 3 -> 500ms
    switch (value) {
    case 1:
        play_haptic_milli(100);
        break;
    case 2:
        play_haptic_milli(300);
        break;
    case 3:
        play_haptic_milli(500);
        break;
    default:
        LOG_WRN("Haptic write: Invalid value %d", value);
        return len;
    }

    return len;
}

// Public Functions

int haptic_init(void)
{
    if (!gpio_is_ready_dt(&haptic_pin)) {
        LOG_ERR("Haptic GPIO device %s is not ready", haptic_pin.port->name);
        return -ENODEV;
    }

    // Initialize the delayable work item
    k_work_init_delayable(&haptic_off_work, haptic_off_work_handler);
    k_work_init_delayable(&alarm_work, alarm_work_handler);

    LOG_INF("Haptic system initialized");
    return 0;
}

void play_haptic_milli(uint32_t duration)
{
    if (!gpio_is_ready_dt(&haptic_pin)) {
        LOG_ERR("Haptic GPIO device not ready");
        return;
    }

    if (duration == 0) {
        // If duration is 0, ensure the pin is off and we are done. The pending
        // off item is deliberately left alone rather than cancelled: cancelling
        // a running handler sets K_WORK_CANCELING, and work_timeout() drops a
        // submission silently while that bit is set. Letting the item fire is
        // harmless -- it finds the deadline reached and writes 0 to a pin that
        // is already 0 -- and the next pulse moves it with k_work_reschedule().
        k_spinlock_key_t key = k_spin_lock(&haptic_lock);
        haptic_off_at = k_uptime_ticks();
        gpio_pin_set_dt(&haptic_pin, 0);
        k_spin_unlock(&haptic_lock, key);

        LOG_INF("Haptic explicitly stopped (duration 0)");
        return;
    }

    // Configure GPIO pin just before turning it on
    int err = gpio_pin_configure_dt(&haptic_pin, GPIO_OUTPUT);
    if (err) {
        LOG_ERR("Failed to configure haptic pin for output (err %d)", err);
        return;
    }

    if (duration > MAX_HAPTIC_DURATION) {
        LOG_WRN("Requested haptic duration %u exceeds max %d, capping.", duration, MAX_HAPTIC_DURATION);
        duration = MAX_HAPTIC_DURATION;
    }

    LOG_INF("Playing haptic for %u ms", duration);

    // Claim the motor and switch it on under the lock the off handler also
    // takes, so a handler that is already running cannot slip between these two
    // lines and switch the pin straight back off. K_MSEC() converts with
    // k_ms_to_ticks_ceil64(), so the deadline computed here is never later than
    // the timeout scheduled below and the pulse's own handler always ends it.
    k_spinlock_key_t key = k_spin_lock(&haptic_lock);
    haptic_off_at = k_uptime_ticks() + k_ms_to_ticks_ceil64(duration);
    gpio_pin_set_dt(&haptic_pin, 1);
    k_spin_unlock(&haptic_lock, key);

    // Move the single off item to this pulse's deadline. k_work_reschedule()
    // rather than cancel + k_work_schedule(): cancelling a *running* handler
    // sets K_WORK_CANCELING, and k_work_schedule() then silently declines to
    // schedule (kernel/work.c, k_work_schedule_for_queue), which used to leave
    // the pulse with no end scheduled at all.
    k_work_reschedule(&haptic_off_work, K_MSEC(duration));
}

void register_haptic_service(void)
{
    int err = bt_gatt_service_register(&haptic_service);
    if (err) {
        LOG_ERR("Failed to register Haptic GATT service (err %d)", err);
    } else {
        LOG_INF("Haptic GATT service registered");
    }
}

void haptic_off()
{
    gpio_pin_set_dt(&haptic_pin, 0);
}

// The capture alarm.
//
// Its own delayable item rather than a second user of haptic_off_work: that one
// carries the deadline of whichever pulse owns the motor, and a repeat that
// moved it would be the very race the ownership rule above exists to prevent.
// This item schedules *pulses*; each pulse still ends itself through
// play_haptic_milli(), which stays the only way the motor is ever driven.

// Raised and unanswered.
static bool alarm_raised;

// Whether the press currently under way belongs to the alarm. Set when a press
// answers one, cleared when the finger comes off, and never true without a
// press having started it.
static bool alarm_owns_press;

// No lock guards these two. The only caller that clears them is the button,
// whose check_button_level() runs on the system workqueue -- the same queue
// alarm_work runs on, which serialises them. The only caller that sets them is
// the disconnect callback, and it can do nothing but raise an alarm that is
// already raised. A missed pulse would be harmless anyway; a stuck motor would
// not be, and that remains impossible because every pulse ends itself.
static void alarm_work_handler(struct k_work *work)
{
    ARG_UNUSED(work);

    if (!alarm_raised) {
        return;
    }

    play_haptic_milli(ALARM_PULSE_MS);
    k_work_reschedule(&alarm_work, K_MSEC(ALARM_PULSE_MS + ALARM_GAP_MS));
}

void haptic_alarm_start(void)
{
    if (alarm_raised) {
        return;
    }

    alarm_raised = true;
    LOG_WRN("Capture alarm raised");
    k_work_reschedule(&alarm_work, K_NO_WAIT);
}

void haptic_alarm_stop(void)
{
    alarm_owns_press = false;

    if (!alarm_raised) {
        return;
    }

    alarm_raised = false;
    (void) k_work_cancel_delayable(&alarm_work);

    // Ends the pulse that is playing right now. Going through
    // play_haptic_milli(0) rather than haptic_off() moves the deadline too, so a
    // handler still in flight finds it reached and agrees the motor is off.
    play_haptic_milli(0);

    LOG_INF("Capture alarm answered");
}

bool haptic_alarm_active(void)
{
    return alarm_raised;
}

void haptic_alarm_on_disconnect(bool was_recording)
{
    if (!was_recording) {
        return;
    }

    haptic_alarm_start();
}

bool haptic_alarm_owns_button(bool pressed)
{
    if (!pressed) {
        const bool was_ours = alarm_owns_press;

        alarm_owns_press = false;
        return was_ours;
    }

    if (alarm_raised) {
        // Answering clears alarm_owns_press, so claiming the press comes after.
        haptic_alarm_stop();
        alarm_owns_press = true;
    }

    return alarm_owns_press;
}
