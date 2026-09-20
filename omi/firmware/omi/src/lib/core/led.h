#ifndef LED_H
#define LED_H

#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>

// LED color enum for PWM control
typedef enum { LED_RED, LED_GREEN, LED_BLUE } led_color_t;

/**
 * @brief Initialize the LEDs
 *
 * Initializes the LEDs
 *
 * @return 0 if successful, negative errno code if error
 */
int led_start();
void set_led_red(bool on);
void set_led_green(bool on);
void set_led_blue(bool on);
void set_led_pwm(led_color_t color, uint8_t level);
void led_off(void);

/**
 * @brief The only signal code the LED signal characteristic accepts.
 *
 * A named code rather than a bare 1, because the characteristic is an
 * instruction and instructions grow: a later one gets its own number, and a
 * firmware that does not know that number refuses it instead of guessing.
 */
#define ORB_LED_SIGNAL_BLUE_ONCE 1

/**
 * @brief Show one second of blue, once.
 *
 * A signal, not a state: it says *here I am* to somebody who has just looked,
 * and then it is over. It is never triggered by connecting — the firmware
 * cannot tell a deliberate open from an automatic reconnect — so the app asks
 * for it over BLE when it knows which of the two happened.
 *
 * While it runs it owns the LED, and the once-a-second status display leaves
 * it alone. Asking again restarts the second.
 */
void orb_led_signal_blue(void);

/**
 * @brief Whether the one-off signal currently owns the LED.
 *
 * The status display asks this first and does nothing while it is true.
 */
bool orb_led_signal_active(void);

/**
 * @brief Repaint the status display as soon as possible, without waiting.
 *
 * For a thread that has just changed what the display should show and must not
 * be blocked while it happens — the one taking a BLE write. Repainting can
 * sleep, and that thread is servicing a radio.
 */
void orb_led_refresh(void);

#endif
