#include <stdio.h>
#include <uchar.h>

struct inner {
    int x;
    short y;
};

enum color { RED, GREEN, BLUE };

struct sample_s {
    int a;
    char *name;
    struct inner in;
    int arr[4];
    unsigned flags : 3;
    unsigned mode : 5;
    enum color c;
    double d;
};

struct sample_s g_sample;
const char g_ascii[] = "Hello, WinLLDB!";
const char16_t g_wide[] = u"Wide string";
unsigned char g_bytes[32];
unsigned int g_magic = 0xfeedface;
int g_counter;

__attribute__((noinline)) int leaf(int v)
{
    g_counter += v;
    return v * 2;
}

__attribute__((noinline)) int middle(struct sample_s *s, int k)
{
    int local = s->a + k;
    return leaf(local);
}

int main(void)
{
    for (int i = 0; i < 32; i++)
        g_bytes[i] = (unsigned char)i;
    g_sample.a = 5;
    g_sample.name = "sample";
    g_sample.in.x = 1;
    g_sample.in.y = 2;
    for (int i = 0; i < 4; i++)
        g_sample.arr[i] = (i + 1) * 10;
    g_sample.flags = 5;
    g_sample.mode = 17;
    g_sample.c = BLUE;
    g_sample.d = 1.5;
    int r = middle(&g_sample, 3);
    printf("%d %s %d\n", r, g_ascii, (int)g_wide[0]);
    return 0;
}
