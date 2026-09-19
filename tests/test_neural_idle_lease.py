"""A warm model may renew only an untouched lease belonging to live processes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NeuralIdleLeaseTest(unittest.TestCase):
    def test_identity_expiry_preload_and_idle_only_renewal(self):
        source = r'''
#include "neural_idle_lease.h"
#include <assert.h>
static void put(const struct nw_state *s) {
 int fd=open(NW_FILE,O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0);
 assert(write(fd,s,sizeof(*s))==sizeof(*s));close(fd);
}
int main(int argc,char **argv) {
 assert(argc==2);
 uint32_t p=getpid(),now=now_ms();
 struct nw_state s={.magic=NW_MAGIC,.owner=p,.observer=p,.nonce=7,.mode=3,
   .deadline=now+50000,.expected_producer=p,.expected_consumer=p};
 memset(s.tag,37,sizeof(s.tag));
 assert(ni_valid(&s,7,p,p,now));
 assert(!ni_valid(&s,8,p,p,now));assert(!ni_valid(&s,7,p+1,p,now));
 assert(!ni_valid(&s,7,p,p+1,now));
 assert(nw_renew_idle(&s,p,now));assert(s.deadline==now+90000);
 struct nw_state good=s;
 assert(!nw_renew_idle(&s,p+1,now));
 for(unsigned phase=NW_WAKE;phase<=NW_CANCELLED;phase++){
   s=good;s.phase=phase;assert(!nw_renew_idle(&s,p,now));
 }
#define DENY(field,value) s=good;s.field=value;assert(!nw_renew_idle(&s,p,now));
 DENY(prepared,1);DENY(wake_ms,1);DENY(producer,p);DENY(consumer,p);
 DENY(packet_size,10);DENY(accepted,1);DENY(wake_modified,1);
 DENY(modified,1);DENY(frames,1);DENY(ended,1);DENY(final_seen,1);
 DENY(finished,1);DENY(failed,1);DENY(observer,1);DENY(expected_producer,1);
 DENY(expected_consumer,1);DENY(nonce,0);DENY(mode,2);DENY(deadline,now_ms()-1);
 s=good;memset(s.tag,0,sizeof(s.tag));assert(!nw_renew_idle(&s,p,now));
 assert(!ni_valid(&s,7,p,p,now));
 s=good;assert(!ni_valid(&s,7,p,p,now+90000));
 s.deadline=now+90001;assert(!ni_valid(&s,7,p,p,now));
 s=good;s.phase=NW_CANCELLED;assert(ni_valid(&s,7,p,p,now));
 s.prepared=1;assert(!ni_valid(&s,7,p,p,now));
 s=good;s.expected_consumer=1;assert(!ni_valid(&s,7,p,p,now));
 put(&good);assert(ni_read(argv[1],7,p,p)==1);
 int fd=open(NW_FILE,O_RDWR);assert(fd>=0 && !flock(fd,LOCK_EX));
 assert(ni_read(argv[1],7,p,p)==-1);close(fd);
 chmod(NW_FILE,0644);assert(!ni_read(argv[1],7,p,p));chmod(NW_FILE,0600);
 fd=open(NW_FILE,O_WRONLY|O_TRUNC);assert(fd>=0);close(fd);
 assert(!ni_read(argv[1],7,p,p));unlink(NW_FILE);
 assert(!symlink("missing",NW_FILE));assert(!ni_read(argv[1],7,p,p));unlink(NW_FILE);
 assert(!ni_read("no-parent",7,p,p));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(source)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'),
                            '-DNW_DIR="' + tmp + '"', str(p / 'test.c'),
                            '-o', str(p / 'test')], check=True, capture_output=True)
            subprocess.run([str(p / 'test'), str(p / 'shadow.stream')], check=True, timeout=5)
