#include "lib/core/led.h"

#include <zephyr/drivers/pwm.h>
#include <zephyr/logging/log.h>

#include "lib/core/settings.h"
#include "lib/core/utils.h"

LOG_MODULE_REGISTER(led, CONFIG_LOG_DEFAULT_LEVEL);

// Define LED PWM specs from device tree
static const struct pwm_dt_spec led_red = PWM_DT_SPEC_GET(DT_NODELABEL(led_red));
static const struct pwm_dt_spec led_green = PWM_DT_SPEC_GET(DT_NODELABEL(led_green));
static const struct pwm_dt_spec led_blue = PWM_DT_SPEC_GET(DT_NODELABEL(led_blue));

int led_start()
{
    ASSERT_TRUE(pwm_is_ready_dt(&led_red));
    ASSERT_TRUE(pwm_is_ready_dt(&led_green));
    ASSERT_TRUE(pwm_is_ready_dt(&led_blue));
    LOG_INF("LEDs (PWM) started");
    return 0;
}

static void set_led_on_off(const struct pwm_dt_spec *led, bool on)
{
    if (!pwm_is_ready_dt(led)) {
        LOG_ERR("LED PWM device not ready");
        return;
    }

    uint32_t pulse_width_ns = 0;
    if (on) {
        uint8_t ratio = app_settings_get_dim_ratio();
        if (ratio > 100) {
            ratio = 100;
        }
        pulse_width_ns = (led->period * ratio) / 100;
    }

    pwm_set_pulse_dt(led, pulse_width_ns);
}

void set_led_red(bool on)
{
    set_led_on_off(&led_red, on);
}

void set_led_green(bool on)
{
    set_led_on_off(&led_green, on);
}

void set_led_blue(bool on)
{
    set_led_on_off(&led_blue, on);
}

void set_led_pwm(led_color_t color, uint8_t level)
{
    const struct pwm_dt_spec *led;

    switch (color) {
    case LED_RED:
        led = &led_red;
        break;
    case LED_GREEN:
        led = &led_green;
        break;
    case LED_BLUE:
        led = &led_blue;
        break;
    default:
        LOG_ERR("Invalid LED color");
        return;
    }

    if (!pwm_is_ready_dt(led)) {
        LOG_ERR("LED PWM device not ready");
        return;
    }

    if (level > 100) {
        level = 100;
    }

    uint32_t pulse_width_ns = (led->period * level) / 100;
    pwm_set_pulse_dt(led, pulse_width_ns);
}

void led_off(void)
{
    set_led_red(false);
    k_msleep(10);
    set_led_green(false);
    k_msleep(10);
    set_led_blue(false);
}

/*
 * --- The one-off signal ---
 *
 * A single second of blue, asked for over BLE, and deliberately not a side
 * effect of connecting: the firmware cannot tell a phone somebody has just
 * opened from one that reconnected by itself, because both are the same GATT
 * connect. Which of the two it was is the app's knowledge, so the decision is
 * the app's and this is only the means of carrying it out.
 *
 * It owns the LED for as long as it lasts. `set_led_state()` asks
 * `orb_led_signal_active()` before it does anything, so the once-a-second
 * status loop can neither cut the signal short nor repaint it in a charging or
 * a disconnected colour. Blue is set here rather than left to whatever the
 * status display would have shown.
 *
 * Its own timer, too, and not the status loop's: a second measured by a loop
 * that ticks every second is anything between one and two.
 */
#define ORB_LED_SIGNAL_MS 1000

/*
 * Written from the thread that takes the BLE write, read from the main loop.
 * `volatile` because the loop reads it once a second forever and has no other
 * reason to reload it — a compiler that kept it in a register would guard
 * nothing at all.
 */
static volatile bool signal_active = false;

/* From main.c: the status display this signal interrupts and hands back to. */
extern void set_led_state(void);

static void orb_led_signal_end(struct k_work *work)
{
    ARG_UNUSED(work);
    signal_active = false;
    /*
     * Handed back rather than turned off. What should be shown now — nothing,
     * while stealth is on — belongs to the status display, and waiting for its
     * next tick would leave up to a second of darkness on a device that is not
     * silenced at all.
     */
    set_led_state();
}

K_WORK_DELAYABLE_DEFINE(orb_led_signal_work, orb_led_signal_end);

/*
 * Repaint the status display, from a thread that must not be made to wait.
 *
 * `set_led_state()` can call `led_off()`, which sleeps twice for the PWM
 * channels to settle. On the main loop that is nothing; on the thread that
 * takes a BLE write it is twenty milliseconds of a radio not being serviced,
 * and it would put a second caller of the same LEDs on a second thread. Both
 * go away by doing the work where the signal's own timer already runs.
 */
static void orb_led_refresh_now(struct k_work *work)
{
    ARG_UNUSED(work);
    set_led_state();
}

K_WORK_DEFINE(orb_led_refresh_work, orb_led_refresh_now);

void orb_led_refresh(void)
{
    k_work_submit(&orb_led_refresh_work);
}

void orb_led_signal_blue(void)
{
    /* The flag first: a status tick landing between these lines would otherwise
     * paint over the signal before it was ever protected. */
    signal_active = true;
    set_led_red(false);
    set_led_green(false);
    set_led_blue(true);
    k_work_reschedule(&orb_led_signal_work, K_MSEC(ORB_LED_SIGNAL_MS));
}

bool orb_led_signal_active(void)
{
    return signal_active;
}
