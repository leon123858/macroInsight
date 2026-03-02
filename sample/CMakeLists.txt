cmake_minimum_required(VERSION 3.10)
project(MacroSampleTest)

include_directories(include)
add_compile_definitions(TEST_MACRO=42)
add_compile_definitions(TEST_MACRO_2=SIZE_COMPLEX)
add_executable(macro_test src/main.c src/utils.c)
