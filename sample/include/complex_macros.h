#ifndef COMPLEX_MACROS_H
#define COMPLEX_MACROS_H

// 1. Character Literals
#define CHAR_A 'A'
#define CHAR_NEWLINE '\n'
#define CHAR_HEX '\x41'

// 2. Sizeof Evaluations
#define SIZE_INT sizeof(int)
#define SIZE_LONG sizeof(long)
#define SIZE_ARRAY sizeof(int[10])
#define SIZE_COMPLEX (sizeof(int) * 4 + sizeof(char))

// 3. Type Casting
#define CAST_INT (int)3
#define CAST_CHAR (char)65
#define CAST_PTR_TO_INT (long)(void*)0x1234abcd

// 4. Combined / Nested
#define COMBINED_CAST_SIZE ((int)sizeof(int) + CHAR_A)
#define BITWISE_CHAR (CHAR_A | 0x20) // 'a'

#endif // COMPLEX_MACROS_H
