long long foo = __builtin_choose_expr(__builtin_constant_p(0), (long long)(0), -9999LL);
