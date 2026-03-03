/**
 * conditional_scenarios.h
 *
 * Sample header that exercises a wide variety of conditional-compilation
 * patterns.  The macros DEFINED from this file are also declared so that
 * the probe-compile pipeline can evaluate them.
 *
 * The macros used INSIDE #if / #ifdef / … directives below are the ones
 * that the --conditional-macro filter should include in the output.
 */
#ifndef CONDITIONAL_SCENARIOS_H
#define CONDITIONAL_SCENARIOS_H

/* ── 1. Basic #ifdef / #ifndef ─────────────────────────────────────────── */
#define FEATURE_NETWORK  1
#define FEATURE_DISPLAY  1
#define LEGACY_MODE      0

#ifdef FEATURE_NETWORK
#  define NET_BUFFER_SIZE  4096
#endif

#ifndef FEATURE_DISPLAY
#  define DISPLAY_STUB  1
#endif

/* ── 2. Simple #if integer check ────────────────────────────────────────── */
#define VERSION_MAJOR  3
#define VERSION_MINOR  2
#define VERSION_PATCH  1

#if VERSION_MAJOR > 2
#  define API_V3  1
#endif

#if VERSION_MAJOR == 1
#  define COMPAT_V1  1
#endif

/* ── 3. #if with defined() — both forms ────────────────────────────────── */
#define PLATFORM_LINUX   1

#if defined(PLATFORM_LINUX)
#  define PATH_SEP  '/'
#elif defined(PLATFORM_WINDOWS)
#  define PATH_SEP  '\\'
#else
#  define PATH_SEP  '/'
#endif

#if defined PLATFORM_LINUX && !defined(PLATFORM_WINDOWS)
#  define UNIX_LIKE  1
#endif

/* ── 4. Complex boolean expressions ─────────────────────────────────────── */
#define ENABLE_LOGGING    1
#define LOG_LEVEL         3
#define MAX_LOG_LEVEL     5

#if ENABLE_LOGGING && (LOG_LEVEL >= 1) && (LOG_LEVEL <= MAX_LOG_LEVEL)
#  define LOGGING_ACTIVE  1
#endif

#if !ENABLE_LOGGING || LOG_LEVEL == 0
#  define SILENT_MODE  1
#endif

/* ── 5. Multi-line continuation in a directive ──────────────────────────── */
#define DEBUG_MEM     1
#define DEBUG_NET     1
#define DEBUG_FS      0

#if DEBUG_MEM && \
    DEBUG_NET && \
    !DEBUG_FS
#  define DEBUG_ALL_EXCEPT_FS  1
#endif

/* ── 6. Nested defined() and parentheses ───────────────────────────────── */
#define ARCH_ARM    0
#define ARCH_X86    1
#define ARCH_MIPS   0

#if (defined(ARCH_ARM) && ARCH_ARM) || (defined(ARCH_X86) && ARCH_X86)
#  define SUPPORTED_ARCH  1
#endif

/* ── 7. #elif chains ────────────────────────────────────────────────────── */
#define OS_TYPE  2   /* 1=linux 2=win 3=mac */

#if OS_TYPE == 1
#  define OS_NAME  "linux"
#elif OS_TYPE == 2
#  define OS_NAME  "windows"
#elif OS_TYPE == 3
#  define OS_NAME  "macos"
#else
#  define OS_NAME  "unknown"
#endif

/* ── 8. #elifdef / #elifndef (C23 / GCC extension) ─────────────────────── */
#define COMPILER_CLANG  1

#ifdef COMPILER_GCC
#  define COMPILER_NAME  "gcc"
#elifdef COMPILER_CLANG
#  define COMPILER_NAME  "clang"
#elifndef COMPILER_MSVC
#  define COMPILER_NAME  "unknown"
#endif

/* ── 9. Macro used only as integer expression (no defined()) ────────────── */
#define TIMEOUT_MS    500
#define RETRY_COUNT   3

#if TIMEOUT_MS
#  define HAS_TIMEOUT  1
#endif

#if RETRY_COUNT > 0
#  define RETRIES_ENABLED  1
#endif

/* ── 10. Comment stripping — inline block comment inside directive ───────── */
#define CACHE_ENABLED    1
#define CACHE_SIZE_KB   256

#if CACHE_ENABLED /* runtime toggled */ && CACHE_SIZE_KB > 0
#  define CACHE_ACTIVE  1
#endif

/* ── 11. NOT conditional — these should NOT appear in the scanner output ── */
/* These macros are only used in regular code / string operations, not in #if */
#define VERSION_STRING   "3.2.1"            /* string — not in any #if */
#define COPYRIGHT_YEAR   2024              /* integer, but only used in printf */
#define STRINGIFY(x)     #x                /* function-like macro */
#define CONCAT(a, b)     a##b              /* function-like macro */

#endif /* CONDITIONAL_SCENARIOS_H */
