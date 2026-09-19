#include "endpoint_active.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
static void feed(struct endpoint_active *e,int voice,unsigned n) {
    while(n--)assert(endpoint_tick(e,voice)==EP_LISTEN);
}
int main(void) {
    struct endpoint_active e={0};
    feed(&e,1,30);feed(&e,0,150);feed(&e,1,40);feed(&e,0,199);
    assert(endpoint_tick(&e,0)==EP_QUIET); /* A 1.5 s mid-sentence pause survives. */
    assert(endpoint_tick(&e,1)==EP_QUIET); /* Terminal state cannot reopen. */
    e=(struct endpoint_active){0};feed(&e,1,30);feed(&e,0,150);
    feed(&e,1,9);feed(&e,0,40);
    assert(endpoint_tick(&e,0)==EP_QUIET); /* 90 ms burst did not reset time. */
    e=(struct endpoint_active){0};feed(&e,1,30);feed(&e,0,195);
    feed(&e,1,12);feed(&e,0,199);
    assert(endpoint_tick(&e,0)==EP_QUIET); /* A word starting at the edge survives. */
    e=(struct endpoint_active){0};feed(&e,1,30);feed(&e,0,195);
    feed(&e,1,9);assert(endpoint_tick(&e,0)==EP_QUIET);
    e=(struct endpoint_active){0};feed(&e,0,799);
    assert(endpoint_tick(&e,0)==EP_NO_SPEECH);
    e=(struct endpoint_active){0};
    for(unsigned i=0;i<79;i++) {feed(&e,1,9);feed(&e,0,1);}
    feed(&e,1,9);assert(endpoint_tick(&e,0)==EP_NO_SPEECH);
    e=(struct endpoint_active){0};feed(&e,1,1999);
    assert(endpoint_tick(&e,1)==EP_LIMIT);
    e=(struct endpoint_active){0};assert(endpoint_wall(&e,8000)==EP_NO_SPEECH);
    feed(&e,1,12);assert(endpoint_wall(&e,19999)==EP_LISTEN);
    assert(endpoint_wall(&e,20000)==EP_LIMIT); /* Missing callbacks cannot hang. */
    e=(struct endpoint_active){0};assert(endpoint_tick(&e,-1)==EP_INVALID);
    puts("PASS: pause, noise debounce, onset at deadline, short bursts, no speech, hard limits, invalid VAD");
    return 0;
}
