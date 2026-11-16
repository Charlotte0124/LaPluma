# -*- coding: utf-8 -*-
"""L08 用户态内存管理 · 练习型讲义（代码 + 例题运算 + 结构图为主）。

来源：课件 L08_User-SpaceMemoryManagement.pdf（78 页）。结构图按课件概念自绘，
课件里的实验（data/BSS 体积、地址打印、爆栈、两次 malloc 差值）都写成可跑的最小程序。

2026-11-16 返工：理论型改成练习型（每节至少一段代码或一道例题），一节一页。
"""

_AXIS = """<svg viewBox="0 0 620 170" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <path d="M580 20 L580 150" stroke="#6E6B61" stroke-width="1.1" marker-end="url(#ax)"/>
  <text x="592" y="18" fill="#A8A498" font-size="9">高地址</text>
  <rect x="120" y="20" width="300" height="18" fill="#161614" stroke="#2A2A24"/><text x="270" y="33" text-anchor="middle" fill="#F4F1E6" font-size="9">栈 stack（向下长，每线程一份）</text>
  <rect x="120" y="42" width="300" height="18" fill="#0F0F0D" stroke="#2A2A24"/><text x="270" y="55" text-anchor="middle" fill="#6E6B61" font-size="9">未分配地址空间（空洞）</text>
  <rect x="120" y="64" width="300" height="18" fill="#161614" stroke="#2A2A24"/><text x="270" y="77" text-anchor="middle" fill="#F4F1E6" font-size="9">堆 heap（向上长，malloc 的地盘）</text>
  <rect x="120" y="86" width="300" height="18" fill="#161614" stroke="#2A2A24"/><text x="270" y="99" text-anchor="middle" fill="#F4F1E6" font-size="9">BSS（未初始化的全局/静态变量）</text>
  <rect x="120" y="108" width="300" height="18" fill="#161614" stroke="#2A2A24"/><text x="270" y="121" text-anchor="middle" fill="#F4F1E6" font-size="9">data（已初始化的全局/静态变量）</text>
  <rect x="120" y="130" width="300" height="18" fill="#1C1B13" stroke="#E7C246"/><text x="270" y="143" text-anchor="middle" fill="#E7C246" font-size="9">常量 + 程序代码 TEXT（只读）</text>
  <text x="14" y="150" fill="#A8A498" font-size="9">低地址 0x0</text>
  <text x="440" y="60" fill="#6E6B61" font-size="9">↑ 这两块只有一张，所有线程共享</text>
  <text x="440" y="76" fill="#6E6B61" font-size="9">↓ 上面两块可读写，下面两块只读</text>
  <defs><marker id="ax" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#6E6B61"/></marker></defs>
</svg>"""

_STK = """<svg viewBox="0 0 620 165" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="16" fill="#A8A498" font-size="10">调用 fun1(u,v) 时的栈（栈从高地址往下长）</text>
  <rect x="14" y="24" width="250" height="20" fill="#161614" stroke="#2A2A24"/><text x="139" y="38" text-anchor="middle" fill="#F4F1E6" font-size="9">main 的局部变量 a=1, b=2</text>
  <rect x="14" y="48" width="250" height="20" fill="#161614" stroke="#2A2A24"/><text x="139" y="62" text-anchor="middle" fill="#F4F1E6" font-size="9">实参 u、v（fun1 的参数）</text>
  <rect x="14" y="72" width="250" height="20" fill="#1C1B13" stroke="#E7C246"/><text x="139" y="86" text-anchor="middle" fill="#E7C246" font-size="9">返回地址（fun1 跑完回哪）</text>
  <rect x="14" y="96" width="250" height="20" fill="#161614" stroke="#2A2A24"/><text x="139" y="110" text-anchor="middle" fill="#F4F1E6" font-size="9">实参 x、y（fun2 的参数）</text>
  <rect x="14" y="120" width="250" height="20" fill="#161614" stroke="#2A2A24"/><text x="139" y="134" text-anchor="middle" fill="#F4F1E6" font-size="9">返回地址 + 局部变量 c=10</text>
  <text x="296" y="60" fill="#6E6B61" font-size="9">← 每进一层压一组</text>
  <text x="296" y="80" fill="#6E6B61" font-size="9">← 返回时逐层弹出</text>
  <text x="296" y="122" fill="#E7C246" font-size="9">返回值不在这张表上</text>
  <text x="296" y="140" fill="#6E6B61" font-size="9">它放在寄存器 EAX / RAX</text>
</svg>"""

_HEAP = """<svg viewBox="0 0 620 160" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="16" fill="#A8A498" font-size="10">malloc / free 眼里的堆：每块前面有一个 Header 记账</text>
  <rect x="14" y="26" width="90" height="30" fill="#1C1B13" stroke="#E7C246"/><text x="59" y="45" text-anchor="middle" fill="#E7C246" font-size="9">H | 已用 16B</text>
  <rect x="110" y="26" width="90" height="30" fill="#1C1B13" stroke="#E7C246"/><text x="155" y="45" text-anchor="middle" fill="#E7C246" font-size="9">H | 已用 16B</text>
  <rect x="206" y="26" width="90" height="30" fill="#0F0F0D" stroke="#6E6B61" stroke-dasharray="3 3"/><text x="251" y="45" text-anchor="middle" fill="#6E6B61" font-size="9">空闲块（free 掉的）</text>
  <rect x="302" y="26" width="90" height="30" fill="#1C1B13" stroke="#E7C246"/><text x="347" y="45" text-anchor="middle" fill="#E7C246" font-size="9">H | 已用 16B</text>
  <text x="14" y="76" fill="#A8A498" font-size="10">空闲链表（课件 p.63）：Head 把空闲块串起来</text>
  <rect x="206" y="86" width="90" height="26" fill="#161614" stroke="#2A2A24"/><text x="251" y="103" text-anchor="middle" fill="#F4F1E6" font-size="9">空闲块</text>
  <rect x="330" y="86" width="90" height="26" fill="#161614" stroke="#2A2A24"/><text x="375" y="103" text-anchor="middle" fill="#F4F1E6" font-size="9">空闲块</text>
  <text x="464" y="103" fill="#6E6B61" font-size="9">→ NULL</text>
  <text x="150" y="103" fill="#E7C246" font-size="9">Head →</text>
  <text x="14" y="140" fill="#6E6B61" font-size="9">释放最后一块 → 可以调 brk() 把堆缩回去；释放中间一块 → 只能进空闲链表，堆缩不了</text>
</svg>"""

_GAP = """<svg viewBox="0 0 620 120" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="16" fill="#A8A498" font-size="10">两次 malloc(16) 之间为什么隔着东西</text>
  <rect x="14" y="26" width="80" height="26" fill="#161614" stroke="#2A2A24"/><text x="54" y="43" text-anchor="middle" fill="#F4F1E6" font-size="9">p1 的 16B</text>
  <rect x="98" y="26" width="70" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="133" y="43" text-anchor="middle" fill="#E7C246" font-size="8">Header</text>
  <rect x="172" y="26" width="70" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="207" y="43" text-anchor="middle" fill="#E7C246" font-size="8">Header</text>
  <rect x="246" y="26" width="80" height="26" fill="#161614" stroke="#2A2A24"/><text x="286" y="43" text-anchor="middle" fill="#F4F1E6" font-size="9">p2 的 16B</text>
  <path d="M54 60 L54 74" stroke="#8FA7B8" stroke-width="1"/><path d="M286 60 L286 74" stroke="#8FA7B8" stroke-width="1"/>
  <text x="54" y="88" text-anchor="middle" fill="#8FA7B8" font-size="9">p1</text>
  <text x="286" y="88" text-anchor="middle" fill="#8FA7B8" font-size="9">p2</text>
  <path d="M96 94 L244 94" stroke="#E7C246" stroke-width="1" marker-start="url(#g1)" marker-end="url(#g1)"/>
  <text x="330" y="48" fill="#6E6B61" font-size="9">差值 = 16 + 16 + 对齐填充 &gt; 16</text>
  <text x="330" y="66" fill="#6E6B61" font-size="9">所以「相邻的两次 16B」并不相邻</text>
  <defs><marker id="g1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker></defs>
</svg>"""

LESSON = {
    "code": "CS340",
    "no": "L08",
    "zh": "用户态内存管理",
    "en": "User-Space Memory Management",
    "out": "L08_用户态内存管理_讲义.pdf",
    "sub": "讲义 · 练习型 ｜ 代码 + 例题运算 + 结构图 ｜ 进程内存五块、栈的调用过程、malloc/free 真身与段错误",
    "meta": [
        ("源课件", "L08_User-SpaceMemoryManagement.pdf，78 页（Xuan Xie，MUST）"),
        ("本讲口径", "以代码与推演为主：每节至少一段可跑代码或一道带数的例题，理论只解释为什么这样"),
        ("图", "结构图按课件概念自绘（不再按页裁原图），所以没有外部图片依赖"),
        ("页码口径", "「课件 p.N」指源 PDF 的页序（共 78 页），不是幻灯片编号"),
        ("怎么读", "§1–§2 布局与地址 → §3 只读区 → §4–§6 data/BSS 与上限 → §7–§8 栈 → §9–§11 堆、free 与段错误"),
        ("动手指令", "`gcc -O0 x.c -o x` 后跑 `size ./x` 看 text/data/bss；`ulimit -a` 看资源上限"),
        ("原文在哪", "CS340\\01_讲义\\L08_User-SpaceMemoryManagement.pdf；本讲义只讲，不复制全文"),
    ],

    "sections": [
        {
            "no": "0", "zh": "本讲导读", "en": "How to Use This Handout",
            "lec": "这讲把「进程的内存」从一句话变成一张分区图，再用几段能跑的程序验证图上每一格的脾气：能不能改、能多大、谁负责回收。",
            "body": [
                ("p", "<b>这一节能解决什么。</b>三个具体问题：① 一个变量的地址落在哪一块，为什么改常量会崩；② 同样的数组，加不加初始值为什么文件大小差十倍；③ malloc 和 free 背后各做了什么，为什么中间块释放了堆却不缩。"),
                ("p", "<b>这一节不能解决什么。</b>虚拟内存与分页在 L09；进程间共享内存、内存映射文件不在本讲；分配器的高性能实现（jemalloc 这类）也不在范围。"),
                ("p", "<b>每节都有能算的题</b>：32 位最多能寻址几个字节、大数组让文件涨多少、递归多少层把 10MB 栈吃穿——算不出来就回去把那段代码跑一遍。"),
                ("note", "本讲地图", "五块布局（§1）→ 用地址看穿它（§2）→ 只读区（§3）→ data 与 BSS（§4）→ BSS 不占文件（§5）→ 数组上限（§6）→ 栈（§7）→ 溢出（§8）→ 堆与 malloc（§9）→ free（§10）→ 段错误（§11）。"),
            ],
        },
        {
            "no": "1", "zh": "进程内存的五块", "en": "The Five Segments",
            "lec": "先给一张总表，后面每节都是把其中一块放大。表的第三列最重要——它问的是「这块的容量在编译时就定了吗」，只有常量固定，其余都能变。",
            "body": [
                ("svg", _AXIS, "图 1　地址从低到高：代码与常量（只读）、data、BSS、堆、空洞、栈"),
                ("table", ["内容", "总空间固定？", "只读？", "对应段"],
                 [["常量（constants）", "是", "是", "code 段"],
                  ["全局变量（global variables）", "是", "否", "data / BSS"],
                  ["局部变量（local variables）", "否", "否", "stack"],
                  ["动态分配内存（allocated memory）", "否", "否", "heap"],
                  ["程序代码（program code）", "否（自修改代码除外）", "否（同上）", "code 段"]],
                 ["30%", "24%", "24%", "22%"]),
                ("eg", "课件 p.3 的四个判断题：常量、全局变量、局部变量、动态分配的内存——各自「总空间固定吗」「只读吗」？",
                 ["常量：总空间固定、只读 → 在 code 段，改它必崩",
                  "全局变量：总空间固定、可读写 → data 或 BSS",
                  "局部变量：不固定、可读写 → 栈，随函数进出伸缩",
                  "动态分配：不固定、可读写 → 堆，你要多少给多少（有上限）"],
                 "答案：见上。判据一句话：<b>只有编译期就定死的那一块是固定的</b>（课件 p.3）。"),
                ("p", "课件 p.2 是那张熟面孔：进程内存里放全局变量、局部变量、动态分配的内存、程序代码与常量。课件 p.3 把它变成上面这四个判断题，并留了一个脚注讲「自修改代码」——那就是代码段为什么标「否」。"),
            ],
        },
        {
            "no": "2", "zh": "用地址看穿布局", "en": "Addressing",
            "lec": "这节教你一个办法：把变量的地址打出来，按大小排序，就能自己画出分段图。课件注了一句要紧的话——背地址没意义，看相对位置才有意义。",
            "body": [
                ("code", "c", "/* layout.c —— 四类东西的地址一次性打出来 */\n#include <stdio.h>\n#include <stdlib.h>\nconst char *msg = \"hello\";       /* 常量：进 code 段的只读区 */\nint  g_data = 1;                /* 已初始化全局：data */\nint  g_bss;                     /* 未初始化全局：BSS */\nint main(void) {\n    int  local = 2;                          /* 栈 */\n    char *heap = malloc(16);                 /* 堆 */\n    printf(\"code/rodata %p\\ndata        %p\\nbss         %p\\nheap        %p\\nstack       %p\\n\",\n           (void*)msg, (void*)&g_data, (void*)&g_bss, (void*)heap, (void*)&local);\n    return 0;\n}", "课件 p.6–p.7；用 %p 打印，不同机器上的具体值不同"),
                ("eq", "32 位地址上限 = 0xffffffff = 2<sup>32</sup> − 1 = 4G − 1"),
                ("table_sym", [("width:18%", "符号"), ("width:44%", "读法·含义"), ("width:38%", "单位")],
                 [["0xffffffff", "32 位地址能表示的最大值", "无量纲（地址）"],
                  ["2<sup>32</sup>", "32 位能编出多少个不同地址", "个"],
                  ["4G", "4 GiB = 4 × 2<sup>30</sup> 字节", "字节"],
                  ["1 字节", "一个地址映射的存储单位（课件 p.10）", "字节"]]),
                ("eg", "32 位系统里一个地址对应一个字节。问：一个进程最多能寻址多少字节？为什么实际可用只有约 3GB？",
                 ["2^32 = 4294967296 字节 ≈ 4GB（课件 p.10）",
                  "内核保留 1GB 地址空间（不是占 1GB 内存，是不让用户态用）",
                  "于是用户态约 4G − 1G = 3G"],
                 "答案：4GB 与约 3GB。这条算式后面在 §6（数组上限）与 §11（OOM 停在 3055MB）各用一次。"),
            ],
        },
        {
            "no": "3", "zh": "只读区：改常量为什么崩", "en": "Code and Constants",
            "lec": "代码段与常量区常被当成「不会出事的地方」，其实最容易踩：你想改常量，程序当场崩。这节两个最小例子把结论钉死——只读区只能读。",
            "body": [
                ("code", "c", "/* ro.c —— 两行都能让程序挂掉，注释掉一行再跑另一行 */\nint main(void) {\n    char *s = \"hello\";       /* 指向常量区的只读字符串 */\n    s[4] = '\\0';             /* ① 写常量区 → Segmentation fault */\n\n    unsigned char *code = (unsigned char *)main;\n    code[0] = 0x90;          /* ② 写代码段 → Segmentation fault */\n    return 0;\n}", "课件 p.14–p.16；先读后写：读一个字节没事，写一个字节就崩"),
                ("p", "课件 p.13 讲代码为什么占内存：CPU 要取指令执行，指令必须在内存里；进程也不只绑一段代码，这正是 L02 讲的 exec 能换程序的底气。"),
                ("p", "课件 p.16 给总结三条：代码与常量都只读；运行期不能改；常量存在 code 段且只有唯一一份（相同字面量会被合并），访问靠地址或指针。"),
                ("eg", "`char *s = \"hi\";` 与 `char s[] = \"hi\";` 都能打印 hi，为什么前者改一下就崩、后者没事？",
                 ["前者：s 是指针，指向 code 段的只读常量区 → 写它触发段错误",
                  "后者：s 是栈上的数组，初始化时把字节复制了一份到栈上 → 可写",
                  "两者内容相同、位置不同，所以权限不同（课件 p.15–p.16）"],
                 "答案：一个在只读区、一个在栈上。<b>「字符串常量」和「字符数组」是两回事</b>，改之前先问它在哪。"),
            ],
        },
        {
            "no": "4", "zh": "data 与 BSS：全局变量为什么分两半", "en": "Data Segment and BSS",
            "lec": "全局变量被拆成两半：初始化过的进 data，没初始化的进 BSS。为什么分？因为 BSS 只需记「有多大」，不用把内容存进文件——下一节的实验就是从这里来的。",
            "body": [
                ("q", "Data Segment – containing initialized global and static variables. BSS – containing uninitialized global and static variables. Both spaces will be allocated at the moment that the program starts.", "课件 p.18"),
                ("code", "c", "/* data_vs_bss.c —— 四个变量的地址会两两挨在一起 */\n#include <stdio.h>\nint  global_data = 1;\nint  global_bss;\nint main(void) {\n    static int static_data = 2;   /* 静态局部变量：也在数据段，不在栈上 */\n    static int static_bss;\n    printf(\"data: %p %p\\n\", (void*)&global_data, (void*)&static_data);\n    printf(\"bss : %p %p\\n\", (void*)&global_bss,  (void*)&static_bss);\n    return 0;\n}", "课件 p.19–p.20；两组地址各自相邻，说明同类变量住在同一块"),
                ("p", "课件 p.19 用 global_vs_static.c 证明静态局部变量与全局变量挨着放（只差 4 字节）；p.20 再排四个地址，看到 BSS 的两个在一起、data 的两个在一起。课件 p.18 那句「两块都在程序启动时分配」也要记：局部变量是调用时才分配（§7）。"),
                ("eg", "函数里的 `static int cnt;` 与普通 `int cnt;` 有什么区别？一个函数返回后它的值还在吗？",
                 ["static 局部变量在数据段（BSS），函数进出不重建 → 值会保留",
                  "普通局部变量在栈上，函数返回即回收 → 下次进来是新的一份",
                  "这也解释了为什么 static 局部变量能当「记住上次」的计数器"],
                 "答案：static 的在数据段、值保留；普通的在栈上、函数返回就没了。判据是<b>地址落在哪一块</b>（课件 p.19）。"),
            ],
        },
        {
            "no": "5", "zh": "实验：BSS 不占文件体积", "en": "BSS Size Experiment",
            "lec": "这节是全讲最漂亮的一组实验：同样一个 10 万字节的数组，赋初值可执行文件涨到 1MB，不赋初值文件大小几乎没变。看懂这个，你就明白「大数组尽量别初始化」。",
            "body": [
                ("code", "c", "/* 四个程序：只改两处——大小、有没有初值 */\nchar a[100]      = {10};   /* data_small.c */\nchar a[100000]   = {10};   /* data_large.c */\nchar a[100];               /* bss_small.c  */\nchar a[100000];            /* bss_large.c  */\n\n/* 编译与检查：\n   gcc -O0 data_large.c -o data_large\n   size ./data_large    # 看 text / data / bss 三段各多大 */", "课件 p.21–p.25；-O0 关掉优化，保证数组真的被分配"),
                ("table", ["文件", "data（字节）", "bss（字节）", "text（字节）"],
                 [["bss_small", "260", "132", "836"],
                  ["bss_large", "260", "1000032", "836"],
                  ["data_small", "384", "8", "836"],
                  ["data_large", "1000284", "8", "836"]],
                 ["30%", "24%", "24%", "22%"]),
                ("p", "课件 p.21–p.22 量文件大小：data_large 是 1007174 字节（约 1MB），data_small 只有 7240 字节。课件 p.23–p.24 换成不初始化：两个都是 7130 字节——BSS 对程序来说只是一堆符号，空间等跑起来才分配。"),
                ("eg", "上表里 data_large 与 bss_large 的 data/bss 各差约 100 万字节。为什么两个文件的实际大小却几乎一样？",
                 ["data 段的内容必须存进可执行文件（那 100 万个 0 要写进磁盘）",
                  "bss 段只记「有多大」这一条信息，内容不落盘，启动时才清零",
                  "所以 data_large 文件约 1MB，bss_large 文件仍是几 KB"],
                 "答案：BSS 不占文件、只占内存。这也是 BSS 全称的由来：Block Started by Symbols（课件 p.9、p.24）。"),
            ],
        },
        {
            "no": "6", "zh": "全局数组的上限", "en": "Limits of the Data Segment",
            "lec": "上一节看到 BSS 可以很大，这节告诉你大也有上限。课件用 1GB 能过、2GB 编译报错、3GB 与 4GB 有讲究，把边界摸出来，并给出「32 位约 3GB 用户空间」的结论。",
            "body": [
                ("code", "c", "/* 试着把全局数组开到 2GB —— 编译就过不去 */\nchar a[2UL * 1024 * 1024 * 1024];\nint main(void) { return a[0]; }\n\n/* gcc -O0 global_2gb.c -o global_2gb\n   global_2gb.c:6: error: size of array 'a' is too large */", "课件 p.29；1GB 还能过，2GB 直接编译报错"),
                ("eq", "可用用户地址空间 ≈ 4G − 1G = 3G"),
                ("table_sym", [("width:16%", "符号"), ("width:44%", "读法·含义"), ("width:40%", "单位")],
                 [["4G", "32 位系统的全部地址空间", "字节（GiB）"],
                  ["1G", "内核保留的地址空间（课件 p.31、p.35）", "字节（GiB）"],
                  ["2G", "全局数组的上限（课件 p.31）", "字节（GiB）"],
                  ["3G", "约等于用户态可用地址空间", "字节（GiB）"]]),
                ("eg", "`ulimit -a` 显示 data seg size 是 unlimited，为什么 2GB 的全局数组还是编译不过？",
                 ["ulimit 管的是运行期资源，管不到编译器的「数组太大」判据",
                  "2GB 已逼近 32 位「常量/数据段 + 代码」的可用上限（用户态约 3GB）",
                  "而且这么大一块还要和栈、堆、共享库抢同一片地址空间"],
                 "答案：编译器与地址空间都有硬上限，ulimit 显示 unlimited 不等于能无限开（课件 p.26、p.30–p.31）。"),
            ],
        },
        {
            "no": "7", "zh": "栈：装什么、调用时压什么", "en": "The Stack",
            "lec": "栈这块钱不多但每行都有用：局部变量、函数参数、程序参数、环境变量全在这。它跟着函数调用走——函数进它就长、函数出它就缩，而且内核一次都没参与。",
            "body": [
                ("code", "c", "/* 三层调用：每层压参数与返回地址，返回时逐层弹出 */\nint fun2(int x, int y) { int c = 10; return x + y + c; }\nint fun1(int u, int v) { return fun2(u * 2, v + 1); }\nint main(void) {\n    int a = 1, b = 2;\n    b = fun1(a, b);        /* 返回值经寄存器 EAX 送回，再写回 b */\n    return 0;\n}", "课件 p.35–p.42；返回值走寄存器，不占栈"),
                ("svg", _STK, "图 2　调用栈：每进一层压一组参数与返回地址，返回时逐层弹出"),
                ("p", "课件 p.34 讲局部变量的生命周期：函数被调用时在栈上分配、返回时释放；课件特意强调一句反直觉的话——<b>函数调用过程中内核什么都没做</b>，这套机制是编译器写死的。"),
                ("eg", "递归函数每次调用都会消耗栈，那「栈用了多少」能在编译期算出来吗？为什么？",
                 ["栈大小取决于调用层数、每层参数与局部变量个数",
                  "而层数由运行时输入决定（比如排序的数组长度），编译器算不出来",
                  "所以内核只能预留一块「够大」的空间，超了就抛异常"],
                 "答案：算不出来（课件 p.43）。这条直接解释了 §8 的栈溢出——预留总有尽头。"),
            ],
        },
        {
            "no": "8", "zh": "栈的上限与溢出", "en": "Stack Size and Overflow",
            "lec": "既然预留有尽头，无止境递归就会把栈吃穿。结局很干脆：CPU 抛栈溢出异常，程序终止。这节把两个数字记住——32 位 Linux 约 10MB，一个 int 递归大约能吃多少层。",
            "body": [
                ("code", "c", "/* boom.c —— 没有终止条件的递归，看它怎么死 */\n#include <stdio.h>\nint depth = 0;\nvoid rec(void) {\n    int pad[64];              /* 每层占一块局部空间，加速吃穿栈 */\n    pad[0] = depth++;\n    rec();                    /* 没有出口 */\n}\nint main(void) { rec(); printf(\"depth = %d\\n\", depth); return 0; }\n/* 结果是 Segmentation fault，printf 一行都打不出来 */", "课件 p.44–p.45；每层 64 个 int ≈ 256 字节"),
                ("p", "课件 p.44 问三个问题：栈没空间了怎么办？能不能扩容？无止境递归呢？现行答案是：CPU 捕获异常——栈溢出（stack overflow），程序终止。课件 p.45 给出 32 位 Linux 的栈大小约 10MB。"),
                ("eg", "栈上限 10MB，每层递归占约 256 字节。估算能递归多少层？把每层的 pad 改成 1024 个 int 又会怎样？",
                 ["10MB = 10 × 1024 × 1024 字节 ≈ 1.05 × 10^7 字节",
                  "1.05e7 ÷ 256 ≈ 4 万层 → 四万次左右就崩",
                  "改成 1024 个 int（4096 字节/层）→ 约 2560 层就崩，早了十几倍"],
                 "答案：约 4 万层与约 2560 层（估）。量级对得上就好——重点是<b>每层占用越大，能撑的层数越少</b>，与容量上限无关。"),
            ],
        },
        {
            "no": "9", "zh": "堆与 malloc 的真身", "en": "Heap and malloc",
            "lec": "这节把 malloc 从「神奇的函数」降级成「会记账的包装」：它本身是库函数，真正向内核要空间的是 brk()；而 malloc 在用户态维护自己的数据结构，记录哪块用了、哪块空着。",
            "body": [
                ("q", "\"malloc()\" is a library function declared in \"stdlib.h\". … When \"malloc()\" is called, the \"brk()\" system call is invoked accordingly. But, it doesn't care how \"malloc()\" uses the space.", "课件 p.50–p.51"),
                ("code", "c", "/* gap.c —— 两次 16 字节的差值是多大？ */\n#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\nint main(void) {\n    char *p1 = malloc(16);\n    char *p2 = malloc(16);\n    printf(\"p1=%p p2=%p 差值=%ld\\n\", (void*)p1, (void*)p2, (long)(p2 - p1));\n    free(p1); free(p2);\n    return 0;\n}", "实测差值通常大于 16——中间夹着 malloc 自己的记账结构"),
                ("svg", _GAP, "图 3　两次 malloc(16) 之间夹着 Header：所以「相邻的 16 字节」并不相邻"),
                ("eg", "上面程序实测 p2 − p1 = 32 而不是 16。这 16 字节差额是什么？为什么 free 必须给原地址？",
                 ["差额是每块前面的 Header（记录长度、是否空闲等），还有对齐填充",
                  "free 靠 Header 找块边界；传错地址 → 算错边界 → 堆记账被破坏",
                  "所以只能 free「malloc 返回的那个起始地址」，不能 free 中间指针"],
                 "答案：Header 与对齐（课件 p.55–p.59）。一句话：<b>malloc 给的不只是你申请的那几个字节</b>。"),
            ],
        },
        {
            "no": "10", "zh": "free：两种情形与空闲链表", "en": "Demystifying free",
            "lec": "free 看着只是「还回去」，其实有两种命运：释放最后一块，堆能缩；释放中间一块，堆缩不了——因为后面还占着。课件先给一个错误设计，再给正确方案：空闲链表。",
            "body": [
                ("code", "c", "/* 空闲链表的样子（示意，不是真实现） */\ntypedef struct block {\n    size_t size;              /* 块长，free 靠它找边界 */\n    int    free;              /* 1 = 空闲，0 = 在用 */\n    struct block *next;       /* 只对空闲块有效：串成链表 */\n} block;\n\nblock *Head = NULL;           /* 链表头，末尾是 NULL */\nvoid release(block *b) {      /* 释放中间一块：进链表，不缩堆 */\n    b->free = 1;\n    b->next = Head;\n    Head = b;\n}", "课件 p.59–p.63；释放最后一块才调 brk() 把堆缩回去"),
                ("svg", _HEAP, "图 4　堆的两段记账：每块前的 Header，以及 Head 串起来的空闲链表"),
                ("p", "课件 p.58 讲前提：free 的地址必须是某次 malloc 返回的起始地址。p.60 讲情形一：释放最后一块可调 brk() 缩堆。p.61–p.62 讲情形二：释放中间一块不能缩，于是用 Head 把空闲块串成链表。"),
                ("eg", "堆上有 A、B、C 三块，现在 free(B)。问：堆会缩小吗？B 的空间还能再用吗？",
                 ["堆不会缩——C 还在上面，地址空间只能从顶端还",
                  "B 被标成空闲并挂进链表，下次 malloc 相同大小时可以复用它",
                  "代价是碎片：有空闲块但大小不合适时用不上（§11 的段错误与之无关，但内存会越用越碎）"],
                 "答案：不缩、可复用。判据一句话：<b>只有最顶端那一块能让堆回缩</b>（课件 p.60–p.63）。"),
            ],
        },
        {
            "no": "11", "zh": "OOM 与段错误", "en": "OOM and Segmentation Fault",
            "lec": "最后一节把前面所有分区串成一张「能不能读、能不能写」的表——段错误的直觉从此有依据：碰到不该碰的地址就崩。还会看到一个经典数字：3055MB。",
            "body": [
                ("table", ["地址落在哪", "读", "写", "例子"],
                 [["只读段（代码、常量）", "可以", "崩", "改 \"hello\" 的字节"],
                  ["已分配段（data/BSS/堆/栈）", "可以", "可以", "普通变量赋值"],
                  ["未使用 / 未分配区", "崩", "崩", "解引用 NULL、越界指针"]],
                 ["32%", "14%", "14%", "40%"]),
                ("code", "c", "/* 最经典的一行段错误 */\nchar *ptr = NULL;\nprintf(\"%c\\n\", *ptr);      /* NULL 就是地址 0x00000000，落在未使用区 */\n\n/* 另一个：往代码段写 */\n((unsigned char *)main)[0] = 0;   /* 代码段只读 → 崩 */", "课件 p.75–p.76；判据就是「地址落在哪一块、这次是读还是写」"),
                ("eq", "OOM 停点 ≈ 3G 用户地址空间 × 实测比例 ≈ 3055MB"),
                ("table_sym", [("width:22%", "项"), ("width:42%", "含义"), ("width:36%", "数值")],
                 [["用户地址空间", "32 位系统减去内核保留的 1G", "约 3G"],
                  ["OOM 实测停点", "不停 malloc(1MB) 的程序在 Linux 上的极限", "约 3055MB"],
                  ["短差", "3G − 3055MB ≈ 实际可用的余量损耗", "约 17MB"]]),
                ("eg", "为什么 `char *p = NULL; *p;` 一定崩，而 `char *p = malloc(1); p[100] = 'x';` 有时不崩？",
                 ["NULL = 地址 0，一定落在「未使用区」 → 必崩",
                  "p[100] 越界到了堆里另一块的 Header 或别的数据 → 那块通常是已分配区，写它能成功",
                  "但它破坏了堆记账，崩溃会在后面某次 free 时才爆发"],
                 "答案：因为判据是「地址落在哪一块」，不是「有没有越界」（课件 p.73–p.77）。这也是越界最讨厌的地方：<b>它不一定当场报错</b>。"),
            ],
        },
    ],

    "summary": {
        "no": "12", "zh": "本讲小结", "en": "Takeaways",
        "lec": "收口用一张表：每行配一个能跑或能算的动作。",
        "head": ["记住什么", "一句话", "怎么自查"],
        "head_widths": ["20%", "52%", "28%"],
        "rows": [
            ["五个分区", "代码/常量、data、BSS、堆、栈", "跑 layout.c 排地址"],
            ["32 位 4GB", "2^32 字节，减去内核 1GB", "算一遍 §2 那道"],
            ["只读区", "代码与常量只能读", "跑 ro.c 两次各崩一处"],
            ["data 与 BSS", "初始化进 data、未初始化进 BSS", "跑 data_vs_bss.c 看两两相邻"],
            ["BSS 不占文件", "只记大小，内容不落盘", "size 看 data 与 bss 列"],
            ["数组上限", "全局数组 2GB 编译就报错", "试 global_2gb.c"],
            ["栈", "每层压参数与返回地址，返回值走 EAX", "画图 2 三层调用"],
            ["栈溢出", "10MB 上限，递归不止就崩", "算 §8 那道层数"],
            ["malloc / brk", "库函数包装系统调用", "算两次 malloc 的差值"],
            ["free", "只有顶端那块能缩堆", "推 A/B/C 那道"],
            ["段错误", "看地址落在哪、读还是写", "判 NULL 与越界那两行"],
        ],
        "tail": "一句话收口：<b>同样是「一个变量」，落在哪一块决定了它能不能改、能多大、谁负责回收</b>——所以先问地址，再问权限。",
    },

    "quiz": {
        "no": "13", "zh": "自测", "en": "Self-check",
        "lec": "六题只用本讲内容：前三题判分区与上限，后三题判栈、malloc/free 与段错误。",
        "items": [
            ("进程内存从低到高有哪几段？哪几段是只读的？",
             "答：程序代码、常量、data、BSS、堆、栈（顺序见课件 p.8–p.9）；只有代码段与常量区只读（课件 p.16）。回看 §1、§3。"),
            ("32 位系统一个进程最多寻址多少？为什么用户态只有约 3GB？",
             "答：2^32 字节 = 4GB（课件 p.10）；内核保留 1GB 地址空间，所以用户态约 3GB（课件 p.31、p.71）。回看 §2、§6。"),
            ("`char a[100000] = {10};` 让程序涨到 1MB，`char a[100000];` 却几乎不变，为什么？",
             "答：前者在 data 段，内容必须进文件；后者在 BSS，只记大小，运行时才分配（课件 p.21–p.25）。回看 §5。"),
            ("函数调用时栈上压了什么？返回值放在哪？",
             "答：局部变量、实参、返回地址（课件 p.35–p.40）；返回值在寄存器 EAX（课件 p.41）。回看 §7。"),
            ("malloc 与 brk 的分工是什么？为什么两次 malloc(16) 的地址差大于 16？",
             "答：malloc 是库函数，底层靠 brk 向内核扩堆（课件 p.50–p.51）；两块之间夹着 Header 与对齐填充（课件 p.55–p.59）。回看 §9。"),
            ("free 一块「中间的」内存时堆会缩小吗？为什么 NULL 解引用必崩？",
             "答：不会缩，只有顶端那块能让堆回缩，中间块进空闲链表（课件 p.60–p.63）；NULL 就是地址 0，落在未使用区，读写都崩（课件 p.75）。回看 §10、§11。"),
        ],
    },

    "glossary": {
        "no": "14", "zh": "术语表", "en": "Glossary",
        "lec": "本讲术语按首次出现排；英文是课件原词，查文档与搜报错都用它。",
        "rows": [
            ("分段", "segmentation", "课件 p.8", "把内存切成不同段"),
            ("程序代码段", "TEXT segment", "课件 p.9", "代码与常量，只读"),
            ("数据段", "DATA segment", "课件 p.9", "已初始化的全局/静态变量"),
            ("BSS", "Block Started by Symbols", "课件 p.9", "未初始化的全局/静态变量"),
            ("常量", "constants", "课件 p.15", "只读，存于 code 段，只有一份"),
            ("局部变量", "local variables", "课件 p.33", "存于栈，函数返回即回收"),
            ("栈", "stack", "课件 p.33", "函数调用区，向下生长"),
            ("返回地址", "return address", "课件 p.36", "函数跑完回到哪一行"),
            ("栈溢出", "stack overflow", "课件 p.44", "栈空间耗尽，程序终止"),
            ("堆", "heap", "课件 p.47", "动态分配区，向上生长"),
            ("动态分配", "dynamic allocation", "课件 p.47", "运行时申请内存"),
            ("系统调用 brk", "brk()", "课件 p.51", "向内核扩或缩堆"),
            ("块头", "header", "课件 p.59", "每块前的记账结构，free 靠它算边界"),
            ("空闲链表", "list of free blocks", "课件 p.63", "free 掉的块被 Head 串起来"),
            ("内存不足", "out of memory", "课件 p.69", "堆要不到空间，32 位停在约 3055MB"),
            ("段错误", "segmentation fault", "课件 p.73", "访问了不允许访问的地址"),
            ("解引用", "de-reference", "课件 p.77", "按地址取内容"),
            ("地址空间", "address space", "课件 p.10", "进程可寻址的范围"),
            ("全局变量", "global variables", "课件 p.18", "程序启动即分配"),
            ("静态变量", "static variables", "课件 p.19", "与全局变量同类存储，作用域不同"),
            ("只读区", "read-only region", "课件 p.16", "代码与常量所在的区，写即崩"),
        ],
    },

    "appendix": {
        "no": "15", "zh": "附录", "en": "Appendix",
        "lec": "一张命令速查加一组误解。速查那几条在实验里直接用。",
        "symbols": [
            ("%p", "printf 打印地址的格式符", "课件 p.6"),
            ("0xffffffff", "32 位最大地址", "课件 p.11"),
            ("size ./prog", "查看 text / data / bss 三段大小", "课件 p.25"),
            ("ulimit -a", "查看资源限制（含 data seg size）", "课件 p.26、p.30"),
            ("brk()", "扩/缩堆的系统调用", "课件 p.51"),
            ("malloc / free", "申请与释放堆内存", "课件 p.50、p.58"),
            ("EAX / RAX", "Intel 存放返回值的寄存器", "课件 p.41"),
            ("NULL", "地址 0，落在未使用区", "课件 p.75"),
        ],
        "myths_title": "常见误解",
        "myths": [
            "以为局部变量可以很大：栈只有约 10MB，几 MB 的局部数组就爆。",
            "以为 BSS 大会让程序文件变大：BSS 只记大小，内容不落盘。",
            "以为 malloc 就是系统调用：它是库函数，底层才调 brk。",
            "以为 free 一定把内存还给系统：只有顶端那块能让堆回缩，中间块进空闲链表。",
            "以为越界一定会当场崩：落在已分配区时不会崩，账坏了要等下次 free 才爆发。",
        ],
    },

    "tail": [],
}
