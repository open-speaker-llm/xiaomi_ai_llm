/* S12A system1 ROM 1.76.54: copy the first 160-sample DNN output plane.
 * Calls the original function unchanged; never opens or pauses the microphone.
 * Requires the verified ARM32 libxaudio ABI, not the kernel's aarch64 ABI.
 */
#define _GNU_SOURCE
#include "pcm_ring.h"
#include <dlfcn.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
typedef int (*process_fn)(void *, void *, int, void *, int *);
static process_fn original;
static struct pcm_ring *ring;
__attribute__((constructor)) static void initialize(void) {
    original=(process_fn)dlsym(RTLD_NEXT,"xaudio_wrapper_dnn");
    char exe[256]; ssize_t n=readlink("/proc/self/exe",exe,sizeof(exe)-1);
    if(n<0)return;exe[n]=0;
    if(!original || strcmp(exe,"/usr/bin/mipns-xiaomi"))return;
    /* Do not inject the tap into shell/LED children started by mipns. */
    unsetenv("LD_PRELOAD");
    int fd=open(PCM_RING_PATH,O_RDWR|O_CREAT|O_CLOEXEC|O_NOFOLLOW,0600);
    if(fd<0)return;
    struct stat st;
    if(fstat(fd,&st) || !S_ISREG(st.st_mode) || st.st_uid!=getuid() ||
       fchmod(fd,0600) || ftruncate(fd,sizeof(struct pcm_ring))) {close(fd);return;}
    void *p=mmap(NULL,sizeof(struct pcm_ring),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    close(fd);if(p==MAP_FAILED)return;
    ring=p;memset(ring,0,sizeof(*ring));
    ring->version=1;ring->rate=PCM_RATE;ring->block_samples=PCM_SAMPLES;
    ring->slots=PCM_SLOTS;ring->producer_pid=(uint32_t)getpid();
    __atomic_store_n(&ring->magic,PCM_MAGIC,__ATOMIC_RELEASE);
}
int xaudio_wrapper_dnn(void *h,void *in,int n,void *out,int *length) {
    if(!original)return -1;
    int ret=original(h,in,n,out,length);
    if(!ring || ret)return ret;
    if(!out || !length || n!=640 || *length!=640) {
        __atomic_add_fetch(&ring->errors,1,__ATOMIC_RELAXED);return ret;
    }
    uint32_t f=__atomic_load_n(&ring->published,__ATOMIC_RELAXED);
    struct pcm_block *b=&ring->blocks[f%PCM_SLOTS];
    __atomic_store_n(&b->sequence,f*2+1,__ATOMIC_SEQ_CST);
    memcpy(b->samples,out,sizeof(b->samples));
    __atomic_store_n(&b->sequence,f*2+2,__ATOMIC_RELEASE);
    __atomic_store_n(&ring->published,f+1,__ATOMIC_RELEASE);
    return ret;
}
