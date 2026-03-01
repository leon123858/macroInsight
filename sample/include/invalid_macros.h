#ifndef INVALID_MACROS_H
#define INVALID_MACROS_H

// Variables / Functions that cannot be resolved via integer constant expressions
extern int GLOBAL_VAR;
int my_function(void);

#define INV_GLOBAL GLOBAL_VAR
#define INV_FUNC my_function()
#define INV_STRING "Hello World"
#define INV_ARRAY ((int[]){1, 2, 3})
#define INV_PTR &GLOBAL_VAR
#define INV_FLOAT 3.14159f
#define INV_VAR_ADD (GLOBAL_VAR + 10)

// while
#define INV_WHILE do { \
    int i = 0; \
    while (i < 10) { \
        i++; \
    } \
} while(0);

// Macros evaluating to a type name
#define INV_TYPE int

#endif // INVALID_MACROS_H
