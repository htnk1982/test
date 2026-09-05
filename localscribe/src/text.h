#ifndef LS_TEXT_H
#define LS_TEXT_H
/* UTF-16 helpers are bounded and testable independently of Windows. */
typedef unsigned short U16;
typedef struct { U16 *p; unsigned cap,len; int truncated; } Text;
unsigned ulen(const U16 *s);
void text_init(Text *t,U16 *p,unsigned cap);
void text_add(Text *t,const U16 *s);
void text_num(Text *t,unsigned long long n,unsigned width);
int text_contains_ascii(const U16 *s,const char *needle);
int npu_candidate(const U16 *description,const U16 *manufacturer);
void sanitize_value(U16 *s);
#endif
