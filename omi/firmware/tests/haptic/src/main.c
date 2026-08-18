/*
 * Who owns the motor.
 *
 * A pulse claims the motor until a deadline. The single off-work item is moved
 * to that deadline rather than cancelled and re-scheduled, and a handler that
 * was already running when a newer pulse started must leave the motor alone.
 *
 * That rule was added because the old code could switch the motor off
 * immediately after a new pulse had switched it on, and could leave a pulse
 * with no scheduled end at all. Neither is reachable from outside: the race is
 * a handful of instructions wide, so a test that only pressed buttons would
 * pass either way.
 *
 * So this includes the translation unit under test instead of linking it. That
 * makes the handler and the deadline reachable, and the stale case becomes a
 * function call rather than a coin toss. **Nothing in the firmware is changed,
 * exposed or restructured for this.**
 *
 * The kernel is real. `k_work_reschedule`, `k_spinlock` and `k_uptime_ticks`
 * are Zephyr's own here, which is the half of the rule a pure function could
 * not have shown.
 */

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_emul.h>
#include <zephyr/kernel.h>
#include <zephyr/ztest.h>

#include "haptic.c"

#define MOTOR_PIN DT_GPIO_PIN(DT_NODELABEL(motor_pin), gpios)
#define MOTOR_PORT DEVICE_DT_GET(DT_GPIO_CTLR(DT_NODELABEL(motor_pin), gpios))

/** Whether the motor is being driven, read back from the emulated pin. */
static bool motor_on(void)
{
    int level = gpio_emul_output_get(MOTOR_PORT, MOTOR_PIN);

    zassert_true(level >= 0, "the emulated pin could not be read");
    return level == 1;
}

/* What the firmware does at boot, and without which the off-work has no
 * handler. Called once for the suite, exactly as `main()` calls it once. */
static void *init_haptic(void)
{
    zassert_ok(haptic_init(), "the haptic system did not initialise");
    return NULL;
}

static void reset_haptic(void *fixture)
{
    ARG_UNUSED(fixture);

    /* Whatever a previous test left behind. */
    (void) k_work_cancel_delayable_sync(&haptic_off_work, &(struct k_work_sync){0});
    play_haptic_milli(0);
    zassert_false(motor_on(), "a test started with the motor still on");
}

ZTEST_SUITE(haptic_ownership, NULL, init_haptic, reset_haptic, NULL, NULL);

/* A — a pulse ends when its own deadline is reached. */
ZTEST(haptic_ownership, test_a_pulse_ends_at_its_deadline)
{
    play_haptic_milli(50);
    zassert_true(motor_on(), "the pulse did not start");

    k_sleep(K_MSEC(20));
    zassert_true(motor_on(), "the pulse ended early");

    k_sleep(K_MSEC(60));
    zassert_false(motor_on(), "the pulse never ended");
}

/*
 * B — the rule this exists for.
 *
 * A handler belonging to a pulse that is over runs while a newer pulse owns the
 * motor. It must do nothing. Before the fix it called `haptic_off()`
 * unconditionally, which switched the motor off in the middle of the new pulse.
 */
ZTEST(haptic_ownership, test_b_a_stale_handler_leaves_a_newer_pulse_alone)
{
    play_haptic_milli(10);
    k_sleep(K_MSEC(30));
    zassert_false(motor_on(), "the first pulse should be over");

    /* The newer pulse claims the motor. */
    play_haptic_milli(500);
    zassert_true(motor_on(), "the second pulse did not start");

    /* The older pulse's handler, arriving late. */
    haptic_off_work_handler(&haptic_off_work.work);

    zassert_true(motor_on(), "a stale handler switched off a pulse that had not ended");
}

/* C — and that newer pulse still ends on its own deadline afterwards. */
ZTEST(haptic_ownership, test_c_the_newer_pulse_still_ends_itself)
{
    play_haptic_milli(60);
    haptic_off_work_handler(&haptic_off_work.work);
    zassert_true(motor_on(), "the stale handler ended it after all");

    k_sleep(K_MSEC(90));
    zassert_false(motor_on(), "the pulse outlived its deadline");
}

/*
 * D — a new pulse moves the deadline rather than adding a second one.
 *
 * The old code cancelled the pending item and scheduled a new one. Cancelling a
 * *running* handler sets K_WORK_CANCELING, and a submission is dropped while
 * that bit is set, which could leave a pulse with nothing scheduled to end it.
 * What is checked here is the visible half: one item, moved.
 */
ZTEST(haptic_ownership, test_d_a_new_pulse_moves_the_deadline)
{
    play_haptic_milli(30);
    const int64_t first = haptic_off_at;

    play_haptic_milli(400);
    zassert_true(haptic_off_at > first, "the deadline did not move forward");

    /* The first pulse's due time passes and the motor stays on. */
    k_sleep(K_MSEC(60));
    zassert_true(motor_on(), "the motor went off at the replaced deadline");

    k_sleep(K_MSEC(400));
    zassert_false(motor_on(), "the motor never went off");
}

/*
 * E — the explicit off leaves nothing behind that could bite a later pulse.
 *
 * It deliberately does not cancel the pending item: cancelling a running
 * handler is what caused the trouble. Instead it brings the deadline forward,
 * so the item may fire, find the deadline reached, and write 0 to a pin that is
 * already 0. The next pulse must be unaffected.
 */
ZTEST(haptic_ownership, test_e_an_explicit_off_does_not_poison_the_next_pulse)
{
    play_haptic_milli(500);
    play_haptic_milli(0);
    zassert_false(motor_on(), "the explicit off did not stop the motor");

    /* Whatever was pending is allowed to arrive. */
    k_sleep(K_MSEC(20));

    play_haptic_milli(300);
    zassert_true(motor_on(), "the next pulse did not start");

    k_sleep(K_MSEC(100));
    zassert_true(motor_on(), "a leftover from the explicit off ended the next pulse");

    k_sleep(K_MSEC(250));
    zassert_false(motor_on(), "the pulse never ended");
}

/* The cap is part of the contract and is easy to break while changing timing. */
ZTEST(haptic_ownership, test_the_five_second_cap_still_holds)
{
    const int64_t before = k_uptime_ticks();

    play_haptic_milli(MAX_HAPTIC_DURATION + 1000);

    const int64_t capped = before + k_ms_to_ticks_ceil64(MAX_HAPTIC_DURATION);

    zassert_true(haptic_off_at <= capped + k_ms_to_ticks_ceil64(50), "a request beyond the cap was not capped");

    play_haptic_milli(0);
}
