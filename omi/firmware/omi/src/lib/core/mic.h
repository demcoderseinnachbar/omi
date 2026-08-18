#ifndef MIC_H
#define MIC_H

#include <stdbool.h>
#include <stdint.h>

typedef void (*mix_handler)(int16_t *);

/**
 * @brief Initialize the Microphone
 *
 * Initializes the Microphone
 *
 * @return 0 if successful, negative errno code if error
 */
int mic_start();
void set_mic_callback(mix_handler _callback);

void mic_off();
void mic_on();
void mic_pause();
void mic_resume();
bool mic_is_running();
void mic_set_gain(uint8_t gain_level);

/* True while the mic is in hardware AAD sleep (mic off, waiting for sound).
 * Lets other subsystems (e.g. the status LED) drop to their lowest-power state. */
bool mic_in_aad_sleep(void);

/**
 * @brief Keep the microphone awake for a deliberate recording.
 *
 * While held, the silence timer may not put the mic into hardware AAD sleep, and
 * acquiring the hold wakes it if it is already asleep or on its way there.
 * Releasing does **not** stop the mic; it hands the decision back to the
 * ordinary VAD/AAD logic and restarts its silence clock, so a quiet recording
 * does not end in an immediate sleep.
 *
 * For clients that mean "a person pressed record", not for ambient listening:
 * a held mic clocks the PDM through silence and costs power accordingly. Ambient
 * use should leave this alone and let the mic sleep.
 *
 * Idempotent, and safe from any thread.
 */
void mic_hold_awake(bool active);

/** Whether a recording hold is currently in place. */
bool mic_hold_active(void);
#endif
