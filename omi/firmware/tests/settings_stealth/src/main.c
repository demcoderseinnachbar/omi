/*
 * Stealth lasts for one session of the device.
 *
 * Until 0.0.6 the setting was written to flash and loaded again at boot, so a
 * pendant that had been silenced stayed dark after it was switched off, ran
 * flat or was updated. From 0.0.7 it lives in RAM only: every boot starts with
 * it off, a write changes this session and nothing else, and the record 0.0.6
 * left behind under `omi/stealth` is recognised and dropped unread (ADR-0051 in
 * the Orb repository).
 *
 * So this includes the translation unit under test instead of linking it, the
 * same way `tests/haptic` does. That makes the RAM copy of every setting and
 * the load handler reachable, and a boot becomes what it is on the device:
 * fresh statics, then `app_settings_init()`. **Nothing in the firmware is
 * changed, exposed or restructured for this.**
 *
 * The settings subsystem is real -- `settings_load_subtree()`,
 * `settings_save_one()` and the handler lookup are Zephyr's own. Only the
 * storage underneath is the test's, so that every write can be counted.
 */

#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/util.h>
#include <zephyr/ztest.h>

#include "settings.c"

/* --- A store that remembers what it was given, and counts it ------------- */

struct record {
    bool present;
    char name[32];
    uint8_t value[16];
    size_t len;
};

static struct record records[8];

/* Every save the subsystem passed down to storage, whatever the key. */
static int saves;

static struct record *find(const char *name)
{
    for (size_t i = 0; i < ARRAY_SIZE(records); i++) {
        if (records[i].present && strcmp(records[i].name, name) == 0) {
            return &records[i];
        }
    }
    return NULL;
}

/* What a previous firmware left in flash, before this boot. */
static void preload(const char *name, const void *value, size_t len)
{
    for (size_t i = 0; i < ARRAY_SIZE(records); i++) {
        if (!records[i].present) {
            records[i].present = true;
            strncpy(records[i].name, name, sizeof(records[i].name) - 1);
            memcpy(records[i].value, value, len);
            records[i].len = len;
            return;
        }
    }
    ztest_test_fail();
}

static ssize_t read_record(void *cb_arg, void *data, size_t len)
{
    const struct record *r = cb_arg;
    size_t n = MIN(len, r->len);

    memcpy(data, r->value, n);
    return (ssize_t) n;
}

static int store_load(struct settings_store *cs, const struct settings_load_arg *arg)
{
    ARG_UNUSED(cs);

    for (size_t i = 0; i < ARRAY_SIZE(records); i++) {
        if (records[i].present) {
            settings_call_set_handler(records[i].name, records[i].len, read_record, &records[i], arg);
        }
    }
    return 0;
}

static int store_save(struct settings_store *cs, const char *name, const char *value, size_t val_len)
{
    ARG_UNUSED(cs);

    saves++;
    struct record *r = find(name);

    if (val_len == 0) {
        if (r) {
            r->present = false;
        }
        return 0;
    }
    if (!r) {
        preload(name, value, val_len);
        return 0;
    }
    memcpy(r->value, value, val_len);
    r->len = val_len;
    return 0;
}

static const struct settings_store_itf store_itf = {
    .csi_load = store_load,
    .csi_save = store_save,
};

static struct settings_store store = {.cs_itf = &store_itf};

/* With CONFIG_SETTINGS_CUSTOM the subsystem asks the application for its
 * backend; this is it. */
int settings_backend_init(void)
{
    settings_src_register(&store);
    settings_dst_register(&store);
    return 0;
}

/* --- A boot, as the device has one -------------------------------------- */

/*
 * RAM comes up with the file's own initial values, and then `main()` calls
 * `app_settings_init()`. Resetting the statics to those values is exactly what
 * a restart does to them -- switched off, battery empty, updated or reset.
 */
static void boot(void)
{
    dim_light_ratio = DEFAULT_DIM_LIGHT_RATIO;
    mic_gain = DEFAULT_MIC_GAIN;
    stealth = DEFAULT_STEALTH;
    memset(&rtc_timestamp, 0, sizeof(rtc_timestamp));
    rtc_epoch = 0;
    memset(&lsm6dsl_time_base, 0, sizeof(lsm6dsl_time_base));

    zassert_ok(app_settings_init(), "the settings did not initialise");
}

static void wipe_flash(void *fixture)
{
    ARG_UNUSED(fixture);

    memset(records, 0, sizeof(records));
    saves = 0;
}

ZTEST_SUITE(settings_stealth, NULL, NULL, wipe_flash, NULL, NULL);

/* A -- a device out of the box starts with the light allowed to speak. */
ZTEST(settings_stealth, test_a_a_boot_starts_with_stealth_off)
{
    boot();
    zassert_equal(app_settings_get_stealth(), 0, "a fresh boot came up silenced");
}

/* B -- switching it on and off is immediate, and anything non-zero is on. */
ZTEST(settings_stealth, test_b_on_and_off_within_a_session)
{
    boot();

    app_settings_set_stealth(1);
    zassert_equal(app_settings_get_stealth(), 1, "switching it on did not take");

    app_settings_set_stealth(0);
    zassert_equal(app_settings_get_stealth(), 0, "switching it off did not take");

    /* The BLE handler passes 0 or 1, as it did in 0.0.6; anything else that
     * reaches this function must still mean on, never a third state. */
    app_settings_set_stealth(7);
    zassert_equal(app_settings_get_stealth(), 1, "a non-zero value was not read as on");
}

/* C -- the rule this exists for: nothing reaches storage, so a restart ends it. */
ZTEST(settings_stealth, test_c_a_session_is_never_written_and_ends_with_a_restart)
{
    boot();

    app_settings_set_stealth(1);
    app_settings_set_stealth(0);
    app_settings_set_stealth(1);

    zassert_equal(saves, 0, "a stealth write reached storage");
    zassert_is_null(find("omi/stealth"), "a stealth record was created");

    boot();
    zassert_equal(app_settings_get_stealth(), 0, "stealth survived a restart");
}

/* D -- a device silenced under 0.0.6 is updated: the old record does nothing. */
ZTEST(settings_stealth, test_d_the_record_0_0_6_left_behind_is_ignored)
{
    const uint8_t silenced = 1;

    preload("omi/stealth", &silenced, sizeof(silenced));

    boot();
    zassert_equal(app_settings_get_stealth(), 0, "the retired record silenced the device again");

    /* Ignored, not erased: booting writes nothing at all. */
    zassert_equal(saves, 0, "booting wrote to storage");
    zassert_not_null(find("omi/stealth"), "the retired record was erased");
}

/*
 * E -- and ignoring it is not a failure.
 *
 * Without the branch that recognises the key, the handler would answer -ENOENT
 * and Zephyr would log a set-value failure on every boot of every device that
 * was ever silenced under 0.0.6. The contrast is shown with a key nobody owns.
 */
ZTEST(settings_stealth, test_e_the_retired_key_is_recognised_rather_than_refused)
{
    const struct record silenced = {.present = true, .value = {1}, .len = 1};

    stealth = DEFAULT_STEALTH;
    zassert_ok(settings_set("stealth", silenced.len, read_record, (void *) &silenced), "the retired key was refused");
    zassert_equal(stealth, 0, "the retired key was read after all");

    zassert_equal(settings_set("no_such_setting", silenced.len, read_record, (void *) &silenced),
                  -ENOENT,
                  "an unknown key was accepted, so the contrast above shows nothing");
}

/* F -- the settings beside it are untouched, and still survive a restart. */
ZTEST(settings_stealth, test_f_the_other_settings_are_unaffected)
{
    const uint8_t ratio = 30;
    const uint8_t gain = 3;
    const uint8_t silenced = 1;

    preload("omi/dim_ratio", &ratio, sizeof(ratio));
    preload("omi/mic_gain", &gain, sizeof(gain));
    preload("omi/stealth", &silenced, sizeof(silenced));

    boot();
    zassert_equal(app_settings_get_dim_ratio(), ratio, "dim_ratio was not loaded");
    zassert_equal(app_settings_get_mic_gain(), gain, "mic_gain was not loaded");
    zassert_equal(app_settings_get_stealth(), 0, "stealth was loaded");

    /* The store does record a real save -- so the zero counted in C and D is
     * an observation, not a store that never counts. */
    zassert_ok(app_settings_save_dim_ratio(40), "dim_ratio could not be saved");
    zassert_equal(saves, 1, "the dim_ratio save did not reach storage");

    app_settings_set_stealth(1);
    zassert_equal(saves, 1, "the stealth write reached storage");

    boot();
    zassert_equal(app_settings_get_dim_ratio(), 40, "dim_ratio did not survive the restart");
    zassert_equal(app_settings_get_mic_gain(), gain, "mic_gain did not survive the restart");
    zassert_equal(app_settings_get_stealth(), 0, "stealth survived the restart");
}
