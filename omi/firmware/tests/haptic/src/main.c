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

/*
 * The capture alarm.
 *
 * A second suite in this file rather than a directory of its own, because the
 * alarm is the same motor under the same ownership rule -- and because a pattern
 * that repeats is the first thing in this firmware to ask `play_haptic_milli()`
 * for a pulse while an earlier one may still be pending. The rule proved above
 * is exactly what has to keep holding.
 *
 * What is deliberately *not* here: `_transport_disconnected()` and
 * `check_button_level()`. Both live in translation units that reach the radio,
 * the microphone, the SD card and `sys_poweroff()`. So the rules they carry are
 * expressed as functions the alarm owns -- `haptic_alarm_on_disconnect()` and
 * `haptic_alarm_owns_button()` -- and what remains at each call site is a single
 * line with nothing left to decide.
 */

static void reset_alarm(void *fixture)
{
    ARG_UNUSED(fixture);

    haptic_alarm_stop();
    (void) k_work_cancel_delayable_sync(&haptic_off_work, &(struct k_work_sync){0});
    play_haptic_milli(0);
    zassert_false(haptic_alarm_active(), "a test started with the alarm still raised");
    zassert_false(motor_on(), "a test started with the motor still on");
}

ZTEST_SUITE(haptic_alarm, NULL, init_haptic, reset_alarm, NULL, NULL);

/* Losing the link mid-recording is the whole reason this exists. */
ZTEST(haptic_alarm, test_a_disconnect_while_recording_raises_the_alarm)
{
    haptic_alarm_on_disconnect(true);

    zassert_true(haptic_alarm_active(), "the alarm was not raised");
}

/* Losing the link at rest is not a failure and must stay silent. */
ZTEST(haptic_alarm, test_b_a_disconnect_at_rest_raises_nothing)
{
    haptic_alarm_on_disconnect(false);

    zassert_false(haptic_alarm_active(), "an idle disconnect raised an alarm");

    k_sleep(K_MSEC(ALARM_PULSE_MS + ALARM_GAP_MS + 100));
    zassert_false(motor_on(), "an idle disconnect drove the motor");
}

/*
 * C -- the pattern, observed rather than assumed.
 *
 * Two full periods are watched at the pin: on for the pulse, off for the gap,
 * on again. A single pulse would pass a test that only looked once.
 */
ZTEST(haptic_alarm, test_c_the_alarm_repeats_until_it_is_answered)
{
    haptic_alarm_on_disconnect(true);

    /* First pulse. */
    k_sleep(K_MSEC(ALARM_PULSE_MS / 2));
    zassert_true(motor_on(), "the first alarm pulse never started");

    /* Its gap. */
    k_sleep(K_MSEC(ALARM_PULSE_MS));
    zassert_false(motor_on(), "the alarm did not pause between pulses");

    /* Second pulse -- this is what makes it a pattern. */
    k_sleep(K_MSEC(ALARM_GAP_MS));
    zassert_true(motor_on(), "the alarm did not repeat");

    zassert_true(haptic_alarm_active(), "the alarm gave up on its own");
}

/* Nobody pressed anything, so it is still going a long time later. */
ZTEST(haptic_alarm, test_d_the_alarm_does_not_time_out)
{
    haptic_alarm_on_disconnect(true);

    k_sleep(K_MSEC((ALARM_PULSE_MS + ALARM_GAP_MS) * 6));

    zassert_true(haptic_alarm_active(), "the alarm stopped without being answered");
}

/* The press answers it, and the motor stops with it. */
ZTEST(haptic_alarm, test_e_a_press_clears_the_alarm_and_the_motor)
{
    haptic_alarm_on_disconnect(true);
    k_sleep(K_MSEC(ALARM_PULSE_MS / 2));
    zassert_true(motor_on(), "the alarm never started");

    (void) haptic_alarm_owns_button(true);

    zassert_false(haptic_alarm_active(), "the press did not clear the alarm");
    zassert_false(motor_on(), "the motor kept running after the alarm was answered");

    /* And it stays clear -- no further pulse is scheduled. */
    k_sleep(K_MSEC((ALARM_PULSE_MS + ALARM_GAP_MS) * 2));
    zassert_false(motor_on(), "a pulse arrived after the alarm was answered");
}

/*
 * F -- the reason the alarm has to own the button at all.
 *
 * Orb reads `1` and `2` -- single and double tap -- as "record". If the press
 * that answers an alarm produced either, answering would start a recording
 * nobody asked for. So for as long as the alarm owns this press, the button
 * reports nothing.
 */
ZTEST(haptic_alarm, test_f_the_answering_press_belongs_to_the_alarm)
{
    haptic_alarm_on_disconnect(true);

    zassert_true(haptic_alarm_owns_button(true), "the alarm did not claim the press");

    /* Held down: still the alarm's, every sampling period. */
    zassert_true(haptic_alarm_owns_button(true), "the alarm let go while still held");
    zassert_true(haptic_alarm_owns_button(true), "the alarm let go while still held");
}

/* The release belongs to the same press, or the tap logic would see half a cycle. */
ZTEST(haptic_alarm, test_g_the_release_belongs_to_it_too)
{
    haptic_alarm_on_disconnect(true);
    (void) haptic_alarm_owns_button(true);

    zassert_true(haptic_alarm_owns_button(false), "the release was not consumed");
}

/* And the moment the finger is off, the button belongs to the person again. */
ZTEST(haptic_alarm, test_h_the_next_press_is_a_normal_one)
{
    haptic_alarm_on_disconnect(true);
    (void) haptic_alarm_owns_button(true);
    (void) haptic_alarm_owns_button(false);

    zassert_false(haptic_alarm_owns_button(true), "a later press was still swallowed");
    zassert_false(haptic_alarm_owns_button(false), "a later release was still swallowed");
}

/* With no alarm raised, the alarm never touches the button. */
ZTEST(haptic_alarm, test_i_without_an_alarm_the_button_is_untouched)
{
    zassert_false(haptic_alarm_owns_button(true), "the button was claimed with no alarm");
    zassert_false(haptic_alarm_owns_button(false), "the release was claimed with no alarm");
}

/*
 * J -- the alarm is not a message, so nothing here needs a connection.
 *
 * Nothing in this suite calls `bt_enable()`; the host is linked but no radio is
 * up and no connection exists. That the alarm runs at all under those conditions
 * is the property, and it is the one the whole slice is for.
 */
ZTEST(haptic_alarm, test_j_the_alarm_needs_no_connection)
{
    haptic_alarm_on_disconnect(true);
    k_sleep(K_MSEC(ALARM_PULSE_MS / 2));

    zassert_true(motor_on(), "the alarm stayed silent without a connection");
    zassert_true(haptic_alarm_active(), "the alarm needs a link it should not need");
}

/*
 * K -- a reconnect must not quietly answer it.
 *
 * There is no clear-on-connect: the alarm has exactly one way out, and that is a
 * finger. Expressed here as the absence of any effect from the only call the
 * transport layer makes into the alarm.
 */
ZTEST(haptic_alarm, test_k_a_reconnect_does_not_clear_the_alarm)
{
    haptic_alarm_on_disconnect(true);

    /* A link comes and goes again with nothing recording. It may not help. */
    haptic_alarm_on_disconnect(false);

    zassert_true(haptic_alarm_active(), "a later idle disconnect cleared the alarm");

    k_sleep(K_MSEC(ALARM_PULSE_MS / 2));
    zassert_true(motor_on(), "the alarm went quiet after a reconnect");
}

/* The three values Orb already writes keep meaning what they meant. */
ZTEST(haptic_alarm, test_l_the_existing_protocol_is_unchanged)
{
    const uint8_t levels[] = {1, 2, 3};
    const uint32_t expected[] = {100, 300, 500};

    for (int i = 0; i < 3; i++) {
        const int64_t before = k_uptime_ticks();

        zassert_equal(haptic_write_handler(NULL, NULL, &levels[i], 1, 0, 0), 1, "level %d was refused", levels[i]);
        zassert_true(motor_on(), "level %d did not start the motor", levels[i]);

        const int64_t want = before + k_ms_to_ticks_ceil64(expected[i]);
        zassert_true(haptic_off_at >= want - k_ms_to_ticks_ceil64(20) &&
                         haptic_off_at <= want + k_ms_to_ticks_ceil64(20),
                     "level %d no longer lasts %u ms",
                     levels[i],
                     expected[i]);

        play_haptic_milli(0);
    }
}

/* An unknown value is still refused rather than guessed at. */
ZTEST(haptic_alarm, test_m_an_unknown_level_still_does_nothing)
{
    const uint8_t unknown = 99;

    zassert_equal(
        haptic_write_handler(NULL, NULL, &unknown, 1, 0, 0), 1, "an unknown level was answered with an error");
    zassert_false(motor_on(), "an unknown level drove the motor");
}
