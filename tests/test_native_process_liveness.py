"""Process ownership checks use isolated children; no device processes are touched."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler needed')
class NativeProcessLivenessTest(unittest.TestCase):
    def run_c(self, source):
        with tempfile.TemporaryDirectory(prefix='native-process-test-') as directory:
            path = Path(directory)
            binary = path / 'check'
            compile_result = subprocess.run(
                ['cc', '-std=c11', '-D_GNU_SOURCE=', '-Wall', '-Wextra', '-Werror',
                 '-I', str(ROOT / 'device/native_asr'),
                 '-I', str(ROOT / 'device/endpoint_probe'),
                 '-DNW_DIR="' + str(path / 'state') + '"', '-x', 'c', '-', '-o', str(binary)],
                input=source, capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_exited_child_is_not_alive_and_remains_waitable(self):
        self.run_c(r'''
#include "control.h"
#include <assert.h>
#include <sys/wait.h>
int main(void) {
    assert(alive((uint32_t)getpid()));
    pid_t pid = fork(); assert(pid >= 0);
    if (!pid) _exit(7);
    siginfo_t info; memset(&info, 0, sizeof(info));
    assert(!waitid(P_PID, (id_t)pid, &info, WEXITED | WNOWAIT));
    assert(info.si_pid == pid);
    int was_alive = alive((uint32_t)pid);
    int status; assert(waitpid(pid, &status, 0) == pid);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 7);
    assert(!was_alive);
    assert(!alive((uint32_t)pid));
    return 0;
}
''')

    def test_zombie_owner_can_be_recovered_without_erasing_route_records(self):
        self.run_c(r'''
#include "native_wake_state.h"
#include "neural_stream.h"
#include "neural_decision.h"
#include "native_wake_recovery.h"
#include <assert.h>
#include <sys/wait.h>
static void save(struct nw_state *state) {
    int fd = open(NW_FILE, O_CREAT | O_TRUNC | O_WRONLY, 0600); assert(fd >= 0);
    assert(write(fd, state, sizeof(*state)) == sizeof(*state)); close(fd);
}
int main(void) {
    assert(!mkdir(NW_DIR, 0700));
    struct nw_state state = {.magic=NW_MAGIC, .owner=getpid(), .phase=NW_CANCELLED};
    save(&state);
    assert(nw_recover_abandoned() == 2); /* A live owner is always preserved. */
    assert(!access(NW_FILE, F_OK));
    assert(!mkdir(NW_DIR "/routes", 0700));
    int fd = open(NW_DIR "/routes/old-denial", O_CREAT | O_WRONLY, 0600); assert(fd >= 0);
    assert(write(fd, "pending\n", 8) == 8); close(fd);
    pid_t pid = fork(); assert(pid >= 0); if (!pid) _exit(0);
    siginfo_t info; memset(&info, 0, sizeof(info));
    assert(!waitid(P_PID, (id_t)pid, &info, WEXITED | WNOWAIT));
    state.owner = (uint32_t)pid; save(&state);
    int recovered = nw_recover_abandoned();
    int status; assert(waitpid(pid, &status, 0) == pid); /* Reap before any assertion can abort. */
    assert(recovered == 0 && access(NW_FILE, F_OK));
    char record[8]; fd = open(NW_DIR "/routes/old-denial", O_RDONLY); assert(fd >= 0);
    assert(read(fd, record, sizeof(record)) == sizeof(record)); close(fd);
    assert(!memcmp(record, "pending\n", sizeof(record)));
    return 0;
}
''')

    def test_stat_parser_distinguishes_exited_live_and_unknown_records(self):
        self.run_c(r'''
#include "process.h"
#include <assert.h>
int main(void) {
    assert(native_process_stat_exited("123 (worker) Z 1 2 3") == 1);
    assert(native_process_stat_exited("123 (worker) X 1 2 3") == 1);
    assert(native_process_stat_exited("123 (worker) x 1 2 3") == 1);
    assert(native_process_stat_exited("123 (name with ) ( and\nnewline) S 1 2") == 0);
    assert(native_process_stat_exited("123 (worker) R 1 2 3") == 0);
    assert(native_process_stat_exited("123 (worker) T 1 2 3") == 0);
    assert(native_process_stat_exited("") == -1);
    assert(native_process_stat_exited("123 (truncated") == -1);
    assert(native_process_stat_exited("123 (worker) Q 1 2") == -1);
    assert(native_process_stat_exited("123 (worker) Z") == -1);
    return 0;
}
''')

    def test_permission_denied_and_unknown_probe_results_preserve_ownership(self):
        self.run_c(r'''
#include <errno.h>
#include <signal.h>
static int result, failure, calls;
static int fake_kill(pid_t pid, int signal_number) {
    (void)pid; (void)signal_number; calls++; errno = failure; return result;
}
#define kill fake_kill
#include "process.h"
#undef kill
#include <assert.h>
int main(void) {
    assert(!native_process_alive(0)); assert(!native_process_alive(1));
    assert(!native_process_alive(UINT32_MAX)); assert(calls == 0);
    result = -1; failure = EPERM; assert(native_process_alive(2147483646u));
    failure = EINVAL; assert(native_process_alive(2147483646u));
    failure = ESRCH; assert(!native_process_alive(2147483646u));
    result = 0; failure = 0; assert(native_process_alive(2147483646u));
    return 0;
}
''')
