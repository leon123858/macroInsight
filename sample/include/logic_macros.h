#ifndef LOGIC_MACROS_H
#define LOGIC_MACROS_H

#define LOGIC_GT (10 > 5)
#define LOGIC_LT (10 < 5)
#define LOGIC_GE (10 >= 10)
#define LOGIC_LE (5 <= 4)
#define LOGIC_EQ (1 == 1)
#define LOGIC_NEQ (1 != 2)
#define LOGIC_AND (LOGIC_GT && LOGIC_EQ)
#define LOGIC_OR  (LOGIC_LT || LOGIC_EQ)
#define LOGIC_NOT (!LOGIC_GT)
#define LOGIC_TERNARY (LOGIC_GT ? 100 : 200)

// Need to define MATH_ADD and MATH_MUL inside the same file or make sure they're included if it evaluates conditionally,
// but for extraction, the preprocessor will have seen the other include.
#define LOGIC_TERNARY_NESTED ((10 + 20) > 20 ? (6 * 7) : (100 / 3))

#endif // LOGIC_MACROS_H
