/* Internal protobuf extension. Only the local IPC carries this marker. */
#ifndef NATIVE_WAKE_TAG_H
#define NATIVE_WAKE_TAG_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define NW_TAG_BYTES 16u
#define NW_TAG_OVERHEAD 28u
/* Field 51000, wire type 2, 24-byte payload = magic + random 128-bit token.
 * Valid unknown protobuf field: an uninstrumented receiver can still parse it.
 * The instrumented receiver strips it before invoking the original unpack. */
static const unsigned char nw_tag_prefix[12]={0xc2,0xf3,0x18,24,'N','W','P','K','0','0','0','1'};
static inline int nw_tag_valid(const unsigned char tag[NW_TAG_BYTES]) {
    unsigned char any=0;for(unsigned i=0;i<NW_TAG_BYTES;i++)any|=tag[i];return any!=0;
}
static inline size_t nw_tag_append(unsigned char *out,size_t capacity,const void *raw,size_t n,const unsigned char tag[NW_TAG_BYTES]) {
    if(!out || !raw || !n || n>256 || capacity<n+NW_TAG_OVERHEAD || !nw_tag_valid(tag))return 0;
    memcpy(out,raw,n);memcpy(out+n,nw_tag_prefix,sizeof(nw_tag_prefix));
    memcpy(out+n+sizeof(nw_tag_prefix),tag,NW_TAG_BYTES);return n+NW_TAG_OVERHEAD;
}
static inline size_t nw_tag_extract(const void *raw,size_t n,unsigned char tag[NW_TAG_BYTES]) {
    if(!raw || n<=NW_TAG_OVERHEAD || n>256+NW_TAG_OVERHEAD)return 0;
    const unsigned char *p=raw;
    if(memcmp(p+n-NW_TAG_OVERHEAD,nw_tag_prefix,sizeof(nw_tag_prefix)))return 0;
    memcpy(tag,p+n-NW_TAG_BYTES,NW_TAG_BYTES);
    return nw_tag_valid(tag)?n-NW_TAG_OVERHEAD:0;
}
#endif
