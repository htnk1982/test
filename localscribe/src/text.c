#include "text.h"
unsigned ulen(const U16 *s){unsigned n=0; if(s)while(s[n])++n;return n;}
void text_init(Text*t,U16*p,unsigned cap){t->p=p;t->cap=cap;t->len=0;t->truncated=0;if(cap)p[0]=0;}
void text_add(Text*t,const U16*s){if(!s)return;while(*s){if(t->len+1>=t->cap){t->truncated=1;if(t->cap)t->p[t->len]=0;return;}t->p[t->len++]=*s++;}if(t->cap)t->p[t->len]=0;}
void text_num(Text*t,unsigned long long n,unsigned width){U16 a[32],b[40];unsigned k=0,j=0;do{a[k++]=(U16)('0'+n%10);n/=10;}while(n&&k<32);if(width>32)width=32;while(j+k<width)b[j++]='0';while(k)b[j++]=a[--k];b[j]=0;text_add(t,b);}
static unsigned lower(unsigned c){return c>='A'&&c<='Z'?c+32:c;}
int text_contains_ascii(const U16*s,const char*needle){if(!s||!needle||!*needle)return 0;for(unsigned i=0;s[i];i++){unsigned j=0;while(needle[j]&&s[i+j]&&lower(s[i+j])==lower((unsigned char)needle[j]))j++;if(!needle[j])return 1;}return 0;}
int npu_candidate(const U16*d,const U16*m){
 if(text_contains_ascii(d,"neural")||text_contains_ascii(d,"AI Boost")||text_contains_ascii(d,"Ryzen AI")||text_contains_ascii(d,"Hexagon"))return 1;
 /* Word-boundary matching avoids treating generic 'input' devices as NPU. */
 for(unsigned i=0;d&&d[i];i++){
  unsigned a=lower(d[i]),b=d[i+1]?lower(d[i+1]):0,c=b&&d[i+2]?lower(d[i+2]):0;
  if(a=='n'&&b=='p'&&c=='u'){
   unsigned before=i?lower(d[i-1]):0,after=d[i+3]?lower(d[i+3]):0;
   int left=(before>='a'&&before<='z')||(before>='0'&&before<='9');
   int right=(after>='a'&&after<='z')||(after>='0'&&after<='9');
   if(!left&&!right)return 1;
  }
 }
 if(text_contains_ascii(d,"IPU")&&(text_contains_ascii(m,"AMD")||text_contains_ascii(m,"Intel")))return 1;
 return 0;
}
void sanitize_value(U16*s){/* Keep metadata on one Markdown line. */
 if(!s)return;for(unsigned i=0;s[i];i++)if(s[i]<32||s[i]=='|'||s[i]=='`'||s[i]==127)s[i]=' ';
}
