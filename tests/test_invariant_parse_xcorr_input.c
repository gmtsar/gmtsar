#include <check.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>

START_TEST(test_buffer_reads_never_exceed_declared_length)
{
    // Invariant: Buffer reads never exceed the declared length
    const char *payloads[] = {
        "normal_input",                     // Valid input
        "A",                                // Boundary case (minimal)
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  // 32 chars - likely exceeds buffer
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  // 64 chars total
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  // 96 chars total
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", // 128 chars total - exploit case
    };
    int num_payloads = sizeof(payloads) / sizeof(payloads[0]);

    for (int i = 0; i < num_payloads; i++) {
        pid_t pid = fork();
        if (pid == 0) {
            // Child process: execute the actual vulnerable function
            char *argv[] = {"test_program", (char *)payloads[i], NULL};
            int argc = 2;
            
            // Redirect stderr to suppress normal program output
            freopen("/dev/null", "w", stderr);
            
            // Call the actual parse_xcorr_input function
            extern void parse_xcorr_input(int argc, char **argv);
            parse_xcorr_input(argc, argv);
            
            // If we get here without crashing, exit cleanly
            _exit(0);
        } else if (pid > 0) {
            int status;
            waitpid(pid, &status, 0);
            
            // Check if child crashed (segfault, bus error, etc.)
            ck_assert_msg(WIFEXITED(status), 
                         "Buffer overflow detected with payload %d (length %zu)", 
                         i, strlen(payloads[i]));
        }
    }
}
END_TEST

Suite *security_suite(void)
{
    Suite *s;
    TCase *tc_core;

    s = suite_create("Security");
    tc_core = tcase_create("Core");

    tcase_add_test(tc_core, test_buffer_reads_never_exceed_declared_length);
    suite_add_tcase(s, tc_core);

    return s;
}

int main(void)
{
    int number_failed;
    Suite *s;
    SRunner *sr;

    s = security_suite();
    sr = srunner_create(s);

    srunner_run_all(sr, CK_NORMAL);
    number_failed = srunner_ntests_failed(sr);
    srunner_free(sr);

    return (number_failed == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}