#ifndef SAMPLE_H
#define SAMPLE_H

// Basic integer macros
#define MAX_BUFFER_SIZE 1024

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_MAX_BUFFER_SIZE = __builtin_choose_expr(__builtin_constant_p(MAX_BUFFER_SIZE), (long long)(MAX_BUFFER_SIZE), -9999LL);
#pragma clang diagnostic pop
#define DEFAULT_TIMEOUT 5000

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_DEFAULT_TIMEOUT = __builtin_choose_expr(__builtin_constant_p(DEFAULT_TIMEOUT), (long long)(DEFAULT_TIMEOUT), -9999LL);
#pragma clang diagnostic pop

// Negative values
#define ERROR_CODE -1

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_ERROR_CODE = __builtin_choose_expr(__builtin_constant_p(ERROR_CODE), (long long)(ERROR_CODE), -9999LL);
#pragma clang diagnostic pop
#define MIN_TEMP -40

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_MIN_TEMP = __builtin_choose_expr(__builtin_constant_p(MIN_TEMP), (long long)(MIN_TEMP), -9999LL);
#pragma clang diagnostic pop

// Hex and bitwise
#define FLAG_A 0x01

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_FLAG_A = __builtin_choose_expr(__builtin_constant_p(FLAG_A), (long long)(FLAG_A), -9999LL);
#pragma clang diagnostic pop
#define FLAG_B 0x02

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_FLAG_B = __builtin_choose_expr(__builtin_constant_p(FLAG_B), (long long)(FLAG_B), -9999LL);
#pragma clang diagnostic pop
#define FLAG_C (FLAG_A | FLAG_B)

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_FLAG_C = __builtin_choose_expr(__builtin_constant_p(FLAG_C), (long long)(FLAG_C), -9999LL);
#pragma clang diagnostic pop

// Complicated expressions
#define A_PLUS_B (10 + 20)

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_A_PLUS_B = __builtin_choose_expr(__builtin_constant_p(A_PLUS_B), (long long)(A_PLUS_B), -9999LL);
#pragma clang diagnostic pop
#define MULTIPLIED (A_PLUS_B * 2)

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_MULTIPLIED = __builtin_choose_expr(__builtin_constant_p(MULTIPLIED), (long long)(MULTIPLIED), -9999LL);
#pragma clang diagnostic pop

// Non-constant macro (function pointer or runtime value)
extern int get_runtime_value(void);
#define RUNTIME_VAL get_runtime_value()

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_RUNTIME_VAL = __builtin_choose_expr(__builtin_constant_p(RUNTIME_VAL), (long long)(RUNTIME_VAL), -9999LL);
#pragma clang diagnostic pop

// Function-like macro (should be ignored by simple regex but let's see)
#define ADD(x, y) ((x) + (y))

// String macro (our probe uses long long, so builtin_constant_p might be true but cast to long long might fail or give pointer address.
// BUT with -Wpointer-to-int-cast ignored, it might just give the address. We will see. User asked for values, typically numbers.)
#define VERSION_STRING "1.0.0"

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wint-conversion"
#pragma clang diagnostic ignored "-Wpointer-to-int-cast"
long long PROBE_VERSION_STRING = __builtin_choose_expr(__builtin_constant_p(VERSION_STRING), (long long)(VERSION_STRING), -9999LL);
#pragma clang diagnostic pop

#endif
