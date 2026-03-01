#ifndef MATH_MACROS_H
#define MATH_MACROS_H

#define MATH_ADD (10 + 20)
#define MATH_SUB (50 - 15)
#define MATH_MUL (6 * 7)
#define MATH_DIV (100 / 3)
#define MATH_MOD (101 % 3)
#define MATH_BIT_AND (0xFF & 0x0F)
#define MATH_BIT_OR  (0xF0 | 0x0F)
#define MATH_BIT_XOR (0xAA ^ 0x55)
#define MATH_LSHIFT  (1 << 4)
#define MATH_RSHIFT  (32 >> 2)
#define MATH_BIT_NOT (~0x0F)
#define MATH_UNARY_PLUS (+50)
#define MATH_UNARY_MINUS (-100)
#define MATH_NESTED  (MATH_ADD * MATH_LSHIFT)

#endif // MATH_MACROS_H
