cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(haptic_ownership)

# The test includes haptic.c rather than linking it, so that the file's own
# statics -- the off-work handler and the deadline it guards -- can be reached.
# Nothing in the firmware is changed or exposed for the test's benefit.
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../../omi/src)
target_sources(app PRIVATE src/main.c)
