#ifndef SAMPLE_H
#define SAMPLE_H

// Basic integer macros
#define MAX_BUFFER_SIZE 1024
#define DEFAULT_TIMEOUT 5000

// Negative values
#define ERROR_CODE -1
#define MIN_TEMP -40

// Hex and bitwise
#define FLAG_A 0x01
#define FLAG_B 0x02
#define FLAG_C (FLAG_A | FLAG_B)

// Complicated expressions
#define A_PLUS_B (10 + 20)
#define MULTIPLIED (A_PLUS_B * 2)

// Non-constant macro (function pointer or runtime value)
extern int get_runtime_value(void);
#define RUNTIME_VAL get_runtime_value()

// Function-like macro (should be ignored by simple regex but let's see)
#define ADD(x, y) ((x) + (y))

// String macro (our probe uses long long, so builtin_constant_p might be true but cast to long long might fail or give pointer address.
// BUT with -Wpointer-to-int-cast ignored, it might just give the address. We will see. User asked for values, typically numbers.)
#define VERSION_STRING "1.0.0"

#endif
