"""Physical-wake metadata correlation is one-shot and cannot cross requests."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeWakeStateTest(unittest.TestCase):
    def test_correlation_cancel_and_private_state(self):
        source = r'''
#include "native_wake_state.h"
#include <assert.h>
int main(void) {
 struct nw_state s={.magic=NW_MAGIC,.owner=getpid(),.deadline=now_ms()+1000};
 assert(nw_live(&s));
 unsigned char packet[8]={0,1,2,3,4,5,6,7};
 assert(!nw_packet(&s,getpid(),packet,8));
 nw_event(&s,getpid(),0x101);assert(s.phase==NW_ARMED);
 nw_event(&s,getpid(),1);assert(s.phase==NW_WAKE);
 assert(!nw_packet(&s,getpid()+1,packet,8));
 assert(!nw_packet(&s,getpid(),packet,257));
 assert(nw_packet(&s,getpid(),packet,8));
 assert(nw_matches(&s,packet,8));assert(!nw_matches(&s,packet,7));
 packet[7]=9;assert(!nw_matches(&s,packet,8));packet[7]=7;
 assert(!nw_packet(&s,getpid(),packet,8));
 assert(!nw_dialog(&s,1,"dialog"));assert(!nw_dialog(&s,getpid(),""));
 assert(nw_dialog(&s,getpid(),"dialog"));assert(s.phase==NW_DIALOG);
 assert(!nw_bound(&s,getpid()+1,"dialog"));assert(!nw_bound(&s,getpid(),"stale"));
 assert(nw_bound(&s,getpid(),"dialog"));assert(!nw_bound(&s,getpid(),"dialog"));
 nw_event(&s,getpid(),0x101);assert(s.phase==NW_BOUND);
 nw_wake(&s,getpid());assert(s.phase==NW_CANCELLED && !nw_live(&s) && s.end_reason==NW_END_REPLACED);
 assert(!nw_matches(&s,packet,8));
 nw_wake(&s,getpid());assert(s.phase==NW_CANCELLED);
 s.phase=NW_BOUND;strcpy(s.dialog,"old");nw_wake(&s,getpid());
 assert(!s.dialog[0] && s.phase==NW_CANCELLED);
 s.phase=NW_ARMED;s.deadline=now_ms()-1;assert(!nw_live(&s));
 s.deadline=now_ms()+1000;s.owner=1;assert(!nw_live(&s));s.owner=getpid();
 s.phase=NW_BOUND;s.mode=1;s.nonce=7;s.observer=getpid();s.producer=s.consumer=getpid();
 s.expected_producer=s.expected_consumer=getpid();s.prepared=s.modified=1;strcpy(s.dialog,"exact");
 assert(nw_can_end(&s,getpid()));assert(!nw_can_end(&s,getpid()+1));
 s.mode=0;assert(!nw_can_end(&s,getpid()));s.mode=2;assert(nw_can_end(&s,getpid()));
 s.mode=3;assert(!nw_can_end(&s,getpid()));
 memset(s.tag,37,sizeof(s.tag));assert(!nw_can_end(&s,getpid()));
 s.accepted=1;assert(nw_can_end(&s,getpid()));
 memset(s.tag,0,sizeof(s.tag));assert(!nw_can_end(&s,getpid()));s.mode=1;
 unsigned char wire[284],tag[16],random_tag[16];memset(random_tag,41,sizeof(random_tag));
 size_t tagged=nw_tag_append(wire,sizeof(wire),packet,8,random_tag);assert(tagged==36);
 assert(nw_tag_extract(wire,tagged,tag)==8 && !memcmp(tag,random_tag,16));
 assert(!nw_tag_append(wire,tagged-1,packet,8,random_tag));
 assert(!nw_tag_extract(wire,tagged-1,tag));
 wire[8]^=1;assert(!nw_tag_extract(wire,tagged,tag));wire[8]^=1;
 memset(wire+tagged-16,0,16);assert(!nw_tag_extract(wire,tagged,tag));
 s.ended=1;assert(!nw_can_end(&s,getpid()));s.ended=0;
 s.final_seen=1;assert(!nw_can_end(&s,getpid()));s.final_seen=0;
 s.finished=1;assert(!nw_can_end(&s,getpid()));s.finished=0;
 s.failed=1;assert(!nw_can_end(&s,getpid()));s.failed=0;
 s.prepared=0;assert(!nw_can_end(&s,getpid()));s.prepared=1;
 s.modified=0;assert(!nw_can_end(&s,getpid()));s.modified=1;
 s.expected_consumer=1;assert(!nw_can_end(&s,getpid()));s.expected_consumer=getpid();
 for(unsigned phase=NW_ARMED;phase<=NW_CANCELLED;phase++){
   s.phase=phase;assert(nw_can_end(&s,getpid())==(phase==NW_BOUND));
 }
 s.phase=NW_ARMED;
 int fd=open(NW_FILE,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);
 assert(write(fd,&s,sizeof(s))==sizeof(s));close(fd);
 struct nw_state t;fd=nw_open(&t);assert(fd>=0);nw_close(fd,NULL);
 chmod(NW_FILE,0644);assert(nw_open(&t)<0);chmod(NW_FILE,0600);
 fd=open(NW_FILE,O_WRONLY|O_TRUNC);assert(fd>=0);close(fd);assert(nw_open(&t)<0);
 unlink(NW_FILE);assert(!symlink("missing",NW_FILE));assert(nw_open(&t)<0);unlink(NW_FILE);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(source)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(ROOT / 'device/endpoint_probe'),
                            '-DNW_FILE="' + str(p / 'state') + '"',
                            str(p / 'test.c'), '-o', str(p / 'test')], check=True,
                           capture_output=True)
            subprocess.run([str(p / 'test')], check=True, timeout=5)
