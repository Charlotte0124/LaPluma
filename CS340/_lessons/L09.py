# -*- coding: utf-8 -*-
"""L09 主存管理 · 练习型讲义（代码 + 例题运算 + 结构图为主）。

来源：课件 L09_MainMemory.pdf（75 页）。结构图按课件概念自绘；课件里的算例（base/limit 区间、
三种适配算法的洞分配、24 字节地址翻译、EAT、内部碎片、页表开销、交换时间）都写成可算的例题。

2026-11-16 返工：理论型改成练习型（每节至少一段代码或一道例题），一节一页。
"""

_BL = """<svg viewBox="0 0 620 140" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <path d="M40 70 L580 70" stroke="#6E6B61" stroke-width="1.1"/>
  <rect x="150" y="52" width="300" height="36" fill="#1C1B13" stroke="#E7C246"/>
  <text x="300" y="75" text-anchor="middle" fill="#E7C246" font-size="10">该进程的合法物理区间</text>
  <text x="150" y="44" fill="#A8A498" font-size="9">base = 300040</text>
  <text x="450" y="44" fill="#A8A498" font-size="9">base + limit − 1 = 420939</text>
  <text x="40" y="96" fill="#6E6B61" font-size="9">低于 base：trap</text>
  <text x="486" y="96" fill="#6E6B61" font-size="9">超出上界：trap</text>
  <path d="M150 70 L150 118" stroke="#E6392F" stroke-width="1" stroke-dasharray="3 3"/>
  <path d="M450 70 L450 118" stroke="#E6392F" stroke-width="1" stroke-dasharray="3 3"/>
  <text x="40" y="132" fill="#8FA7B8" font-size="9">注意 limit 是「长度」不是「最大地址」：最大合法地址要减 1</text>
</svg>"""

_PG = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="14" y="30" width="150" height="26" fill="#161614" stroke="#2A2A24"/><text x="89" y="48" text-anchor="middle" fill="#F4F1E6" font-size="9">逻辑地址 p | d</text>
  <rect x="200" y="14" width="180" height="24" fill="#161614" stroke="#2A2A24"/><text x="290" y="31" text-anchor="middle" fill="#F4F1E6" font-size="9">页号 p（索引页表）</text>
  <rect x="200" y="48" width="180" height="24" fill="#161614" stroke="#2A2A24"/><text x="290" y="65" text-anchor="middle" fill="#F4F1E6" font-size="9">偏移 d（原样保留）</text>
  <rect x="420" y="30" width="180" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="510" y="48" text-anchor="middle" fill="#E7C246" font-size="9">帧号 f | d = 物理地址</text>
  <path d="M166 43 L196 26" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#pg1)"/>
  <path d="M166 65 L196 60" stroke="#6E6B61" stroke-width="1.1"/>
  <path d="M382 26 L416 40" stroke="#E7C246" stroke-width="1.1" marker-end="url(#pg2)"/>
  <text x="14" y="96" fill="#6E6B61" font-size="9">页表在内存里：查一次页表要访存一次，取数据再访存一次 → 所以需要 TLB</text>
  <text x="14" y="114" fill="#6E6B61" font-size="9">偏移 d 全程不变 —— 页与帧大小相同，这是「换号不换内位移」的前提</text>
  <text x="14" y="132" fill="#A8A498" font-size="9">若页面 2<sup>n</sup> 字节、逻辑空间 2<sup>m</sup>：高位 m−n 位是 p，低位 n 位是 d</text>
  <defs>
    <marker id="pg1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker>
    <marker id="pg2" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker>
  </defs>
</svg>"""

_SEG = """<svg viewBox="0 0 620 140" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="14" y="24" width="170" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="99" y="39" text-anchor="middle" fill="#E7C246" font-size="9">逻辑地址 ⟨段号 s, 偏移 d⟩</text>
  <rect x="14" y="70" width="170" height="52" fill="#161614" stroke="#2A2A24"/>
  <text x="99" y="88" text-anchor="middle" fill="#F4F1E6" font-size="9">先验 s &lt; STLR？</text>
  <text x="99" y="106" text-anchor="middle" fill="#6E6B61" font-size="9">不成立 → 非法段，trap</text>
  <text x="240" y="18" fill="#A8A498" font-size="9">段表（每一项：基址 + 长度 + 保护位）</text>
  <rect x="240" y="24" width="200" height="20" fill="#161614" stroke="#2A2A24"/><text x="340" y="38" text-anchor="middle" fill="#F4F1E6" font-size="9">0  代码段  base 1400  len 1000</text>
  <rect x="240" y="48" width="200" height="20" fill="#161614" stroke="#2A2A24"/><text x="340" y="62" text-anchor="middle" fill="#F4F1E6" font-size="9">1  数据段  base 6300  len  400</text>
  <rect x="240" y="72" width="200" height="20" fill="#161614" stroke="#2A2A24"/><text x="340" y="86" text-anchor="middle" fill="#F4F1E6" font-size="9">2  栈      base 4300  len 1100</text>
  <rect x="470" y="48" width="136" height="24" fill="#1C1B13" stroke="#E7C246"/><text x="538" y="65" text-anchor="middle" fill="#E7C246" font-size="9">物理地址 base+d</text>
  <path d="M188 35 L236 34" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#sg1)"/>
  <path d="M444 58 L466 58" stroke="#E7C246" stroke-width="1.1" marker-end="url(#sg2)"/>
  <text x="240" y="112" fill="#6E6B61" font-size="9">段大小可变，物理位置可以不连续、顺序也可以打乱</text>
  <defs>
    <marker id="sg1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker>
    <marker id="sg2" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker>
  </defs>
</svg>"""

_MULTI = """<svg viewBox="0 0 620 140" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="14" y="30" width="130" height="26" fill="#161614" stroke="#2A2A24"/><text x="79" y="48" text-anchor="middle" fill="#F4F1E6" font-size="9">逻辑地址</text>
  <rect x="176" y="30" width="130" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="241" y="48" text-anchor="middle" fill="#E7C246" font-size="9">外层页表 p1</text>
  <rect x="338" y="30" width="130" height="26" fill="#161614" stroke="#2A2A24"/><text x="403" y="48" text-anchor="middle" fill="#F4F1E6" font-size="9">内层页表 p2</text>
  <rect x="500" y="30" width="106" height="26" fill="#161614" stroke="#2A2A24"/><text x="553" y="48" text-anchor="middle" fill="#F4F1E6" font-size="9">帧 + 偏移 d</text>
  <path d="M146 43 L172 43" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#m1)"/>
  <path d="M308 43 L334 43" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#m1)"/>
  <path d="M470 43 L496 43" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#m1)"/>
  <text x="14" y="82" fill="#6E6B61" font-size="9">只有被用到的那几张内层页表才真的占内存 —— 这是多级页表省空间的原因</text>
  <text x="14" y="100" fill="#6E6B61" font-size="9">代价：一次翻译要访存多次（两级 = 三次），所以 TLB 命中更关键</text>
  <text x="14" y="124" fill="#A8A498" font-size="9">32 位 + 1K 页的算例：页号 22 位 = 12 位 p1 + 10 位 p2，偏移 10 位（课件 p.53）</text>
  <defs><marker id="m1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker></defs>
</svg>"""

LESSON = {
    "code": "CS340",
    "no": "L09",
    "zh": "主存管理",
    "en": "Main Memory Management",
    "out": "L09_主存管理_讲义.pdf",
    "sub": "讲义 · 练习型 ｜ 代码 + 例题运算 + 结构图 ｜ 保护、三种分配方案、分页翻译、TLB 与 EAT",
    "meta": [
        ("源课件", "L09_MainMemory.pdf，75 页"),
        ("本讲口径", "以代码与推演为主：每节至少一段代码或一道带数的例题，理论只解释为什么这样算"),
        ("图", "结构图按课件概念自绘（不再按页裁原图），所以没有外部图片依赖"),
        ("页码口径", "「课件 p.N」指源 PDF 的页序（共 75 页），不是幻灯片编号"),
        ("怎么读", "§1–§2 保护与地址 → §3 三种方案 → §4–§5 连续分配与碎片 → §6 分段 → §7–§10 分页（重点）→ §11 页表太大 → §12–§13 交换与芯片"),
        ("动手指令", "`getconf PAGESIZE` 看本机页大小（Linux 常见 4096）；课件 p.30 也给了 getpagesize() 的写法"),
        ("原文在哪", "CS340\\01_讲义\\L09_MainMemory.pdf；本讲义只讲，不复制全文"),
    ],

    "sections": [
        {
            "no": "0", "zh": "本讲导读", "en": "How to Use This Handout",
            "lec": "这讲回答一个问题：多个进程同时要内存，内核怎么把它们塞进去还不打架。三套方案（连续分配、分段、分页）与两个指标（内部/外部碎片），都是能算的。",
            "body": [
                ("p", "<b>这一节能解决什么。</b>三个具体问题：① 一个进程为什么碰不到别人的内存；② 洞怎么挑（first/best/worst-fit）、碎了多少；③ 逻辑地址怎么翻成物理地址，EAT 怎么算。"),
                ("p", "<b>这一节不能解决什么。</b>按需调页与页面置换算法（LRU、clock 这些）是后续内容；用户态的项目内存布局在 L08；具体分配器实现不在本讲。"),
                ("p", "<b>每节都有能算的题</b>：合法区间上下界、每个洞分给谁、逻辑地址变物理地址、EAT 是多少——算不出就回那一节把代码跑一遍。"),
                ("note", "本讲地图", "保护（§1）→ 逻辑地址与 MMU（§2）→ 三种方案（§3）→ 连续分配与三算法（§4）→ 碎片（§5）→ 分段（§6）→ 分页（§7）→ 翻译与 TLB（§8）→ 保护位与共享（§9）→ 页大小权衡（§10）→ 大页表（§11）→ 交换（§12）→ 真实芯片（§13）。"),
            ],
        },
        {
            "no": "1", "zh": "保护：base 与 limit", "en": "Protection: Base and Limit",
            "lec": "先立规矩：一个进程只能碰自己的地址。实现极简单——一对寄存器，CPU 每次生成地址都验一遍，越界就陷入内核。保护是硬件做的，代价几乎为零，这是后面所有方案的地基。",
            "body": [
                ("q", "We can provide this protection by using a pair of base and limit registers. Base: smallest legal physical address. Limit: size of the range of physical address.", "课件 p.4"),
                ("svg", _BL, "图 1　base/limit 的合法性判定：地址必须落在 [base, base+limit) 内"),
                ("code", "c", "/* CPU 每生成一个用户态地址，都过这一关 */\nunsigned long base  = 300040;\nunsigned long limit = 120900;\n\nint legal(unsigned long addr) {\n    return addr >= base && addr < base + limit;   /* 左闭右开 */\n}\n/* 不合法就 trap 到内核，报 addressing error（寻址错误） */", "课件 p.5；limit 是长度，所以上界要写成 base + limit"),
                ("eg", "base = 300040、limit = 120900。问：最大合法地址是多少？地址 300039 与 420940 分别怎样？",
                 ["合法区间是 300040 到 300040 + 120900 − 1 = 420939",
                  "300039 < base → 越界，trap",
                  "420940 = base + limit → 也不合法（右边界开）"],
                 "答案：最大合法地址 420939；两个都越界。这就是 limit「是长度不是最大地址」的直接后果（课件 p.4）。"),
            ],
        },
        {
            "no": "2", "zh": "逻辑地址、物理地址与 MMU", "en": "Logical vs Physical",
            "lec": "这节引入一对必须分清的概念：CPU 生成的是逻辑地址（也叫虚拟地址），内存单元看到的是物理地址，两者之间的换算是硬件 MMU 做的。程序里的地址为什么不是真实地址，答案就在这里。",
            "body": [
                ("q", "Logical address – generated by the CPU during a program execution; also referred to as virtual address. Physical address – refers to a location in the memory unit.", "课件 p.6"),
                ("code", "c", "/* 程序里打印出来的地址，是逻辑地址 */\n#include <stdio.h>\nint g = 1;\nint main(void) {\n    int local = 2;\n    printf(\"%p %p\\n\", (void*)&g, (void*)&local);\n    return 0;\n}\n/* 两次运行 local 的地址可能不同（栈随机化） */\n/* 但程序从来不知道自己被装在哪块物理内存里 */", "课件 p.6–p.8；重定位寄存器把 base 加到每个逻辑地址上"),
                ("p", "课件 p.6 强调：逻辑地址空间与物理地址空间分离，是正确内存管理的核心概念。p.7 给 MMU 的定义——运行时把虚拟地址映射为物理地址的硬件设备。p.8 讲最早的一种映射：把重定位寄存器的值加到每个用户地址上。"),
                ("eg", "重定位寄存器取 14000。某指令要访问逻辑地址 346，实际访问的物理地址是多少？如果进程被搬到 20000，逻辑地址要改吗？",
                 ["物理地址 = 14000 + 346 = 14346",
                  "搬家后物理地址 = 20000 + 346 = 20346，逻辑地址仍是 346",
                  "这正是「程序只见逻辑地址」的好处：搬进程不用改程序（课件 p.8）"],
                 "答案：14346；逻辑地址不变。判据一句话：<b>逻辑地址是程序视角，物理地址是内存视角</b>。"),
            ],
        },
        {
            "no": "3", "zh": "三种分配思路", "en": "Three Approaches",
            "lec": "整个内存管理史可以压成三行：连续分配（整块塞进去）、分段（按逻辑切）、分页（按固定大小切）。这节只要能说出三者的差别与代价——要多大的连续空间、要不要表、碎不碎。",
            "body": [
                ("table", ["方案", "怎么切", "要什么辅助结构", "主要问题"],
                 [["连续分配contiguous allocation", "整个程序放进一块连续内存", "base/limit 寄存器", "外部碎片"],
                  ["分段segmentation", "按逻辑切成段（代码、数据、栈…）", "段表", "外部碎片"],
                  ["分页paging", "切成固定大小的页，装进同样大小的帧", "页表（+TLB）", "内部碎片、页表开销"]],
                 ["26%", "34%", "22%", "18%"]),
                ("p", "课件 p.10 就是这么分的：连续分配是最早的方案，要「找到能装下的地方」；分段让程序按逻辑切段，需要段表追踪；分页把程序切成固定大小的页、装进固定大小的帧，需要页表追踪。课件 p.11 用一张图把三者并排画出形状。"),
                ("eg", "一个 12KB 的程序，内存只剩两块各 8KB 的空闲区。三种方案分别能不能装下？",
                 ["连续分配：不能——要一整块 12KB，两块各 8KB 不连续",
                  "分段：能——代码段 5KB、数据段 3KB、栈 4KB 可以分开放（若每段都 ≤ 8KB）",
                  "分页：能——切成 3 个 4KB 的页，装进两个 8KB 区里的任意三帧"],
                 "答案：连续分配不行，分段与分页都行。这就是「不连续」带来的自由度（课件 p.10–p.11）。"),
            ],
        },
        {
            "no": "4", "zh": "连续分配：三个适配算法", "en": "First / Best / Worst Fit",
            "lec": "连续分配的两个版本，差别在「分区大小是否预先定死」。可变分区要面对「找哪个洞」的问题，这就是三个适配算法的由来。课件给了一道洞分配题，考试常见。",
            "body": [
                ("code", "c", "/* 三个适配算法的最小实现：洞数组 + 请求大小 */\nint first_fit(int *hole, int n, int need) {\n    for (int i = 0; i < n; i++) if (hole[i] >= need) return i;  /* 第一个够大的 */\n    return -1;\n}\nint best_fit(int *hole, int n, int need) {\n    int k = -1;\n    for (int i = 0; i < n; i++)\n        if (hole[i] >= need && (k < 0 || hole[i] < hole[k])) k = i;  /* 最小的够大 */\n    return k;\n}\nint worst_fit(int *hole, int n, int need) {\n    int k = -1;\n    for (int i = 0; i < n; i++)\n        if (hole[i] >= need && (k < 0 || hole[i] > hole[k])) k = i;  /* 最大的 */\n    return k;\n}", "课件 p.16；first/best 在速度与利用率上都优于 worst，best 比 first 慢"),
                ("p", "课件 p.14 讲固定分区：内存预切成若干固定大小的分区，一个分区装一个进程，于是<b>多道程度被分区数锁死</b>（IBM OS/360 MFT）。p.15 讲可变分区：空闲块叫洞（hole），进程到达找个够大的洞，退出就回收并合并相邻空闲区。"),
                ("eg", "洞依次为 10、4、20、18、7、9、12、15 KB，请求 12KB、10KB、9KB（课件 p.17 的题）。用 first-fit 分配这三个请求。",
                 ["12KB：第一个够大的是 20KB（下标 2）→ 切出 12，剩 8",
                  "10KB：扫描到 18KB（下标 3）→ 切出 10，剩 8",
                  "9KB：剩下的洞里 12KB（下标 6）够 → 切出 9，剩 3"],
                 "答案：分别落在原 20、18、12 三个洞。换成 best-fit 结果会不同（12 会挑 12KB 那个洞），自己按同一顺序再走一遍。"),
            ],
        },
        {
            "no": "5", "zh": "碎片：内部与外部", "en": "Fragmentation",
            "lec": "碎片有两种，千万别混：外部的在分区之间（洞太小用不上），内部的在分区里面（给你的比你要的多）。记住这个对应关系，后面看「分页消掉外部碎片」就顺了。",
            "body": [
                ("q", "External Fragmentation – total memory space exists to satisfy a request, but it is not contiguous. Internal Fragmentation – allocated memory may be slightly larger than requested memory.", "课件 p.18"),
                ("table", ["类型", "位置", "典型出现在", "对策"],
                 [["外部碎片external", "空闲分区之间", "连续分配、分段", "紧凑（compaction）或改分页"],
                  ["内部碎片internal", "已分配分区内部", "分页（最后一页填不满）", "减小页大小（但页表变大）"]],
                 ["24%", "24%", "26%", "26%"]),
                ("p", "课件 p.18 还给一个模拟结论：分配了 N 块时，约有 0.5N 块会因碎片损失，约三分之一的内存可能用不上——这就是「50% 规则」。p.19 给外部碎片的对策：紧凑，但要求重定位是动态的，且挪数据代价高。"),
                ("eg", "进程需要 5KB、内存里有三个 2KB 的洞。这是内部还是外部碎片？若页大小 4KB、进程正好 5KB，内部碎片多少？",
                 ["三个 2KB 的洞 → 总量 6KB ≥ 5KB 但不连续 → 外部碎片",
                  "分页时切成 2 页（4KB + 4KB）：第二页只用 1KB，浪费 3KB",
                  "3KB 在分区内部 → 内部碎片"],
                 "答案：前者外部、后者内部。判据一句话：<b>看浪费发生在分区之间还是分区之内</b>（课件 p.18）。"),
            ],
        },
        {
            "no": "6", "zh": "分段：按逻辑切", "en": "Segmentation",
            "lec": "分段贴近程序员的直觉：程序本来按逻辑分成代码、数据、栈、堆（L08 见过的正是这几块）。硬件干脆按「段号 + 偏移」编址，用段表查每段基址与长度。要带走两个寄存器名与一条判据 s < STLR。",
            "body": [
                ("svg", _SEG, "图 2　分段查表：先验段号合法，再用 基址 + 偏移 得到物理地址"),
                ("code", "c", "/* 段表项 + 一次完整翻译 */\ntypedef struct { unsigned long base; unsigned long len; int rwx; } seg_t;\nseg_t st[] = { {1400, 1000, 5}, {6300, 400, 3}, {4300, 1100, 3} };\n#define STLR 3                       /* 段的数量 */\n\nunsigned long translate(unsigned s, unsigned d) {\n    if (s >= STLR)         return -1;  /* 非法段号 */\n    if (d >= st[s].len)    return -1;  /* 段内越界 */\n    return st[s].base + d;\n}\n/* translate(1, 100) → 6300 + 100 = 6400 */", "课件 p.23–p.24；段表每项还带验证位与读写执行权限"),
                ("eg", "用上面那张段表：translate(2, 1200) 与 translate(3, 10) 各返回什么？为什么？",
                 ["(2, 1200)：段 2 长度 1100，偏移 1200 ≥ 1100 → 段内越界，返回 -1",
                  "(3, 10)：3 ≥ STLR(3) → 非法段号，返回 -1",
                  "两个都被保护拦住，区别在「越界」与「非法段」"],
                 "答案：都返回 -1。判据两条：<b>段号 < STLR，偏移 < 段长</b>（课件 p.23）。"),
            ],
        },
        {
            "no": "7", "zh": "分页：页、帧与页表", "en": "Paging",
            "lec": "分页把内存切成固定格子，程序也切成同样大小的块，于是「不连续」不再是问题——任何空帧都能装。代价是页表与内部碎片。先记住三个词：页（逻辑）、帧（物理）、页表（映射）。",
            "body": [
                ("q", "Paging … allows processes physical memory to be discontinuous, and which eliminates problems with fragmentation by allocating memory in equal sized blocks known as pages. … the predominant memory management technique used today.", "课件 p.28"),
                ("table", ["概念", "在哪一侧", "大小", "说明"],
                 [["页page", "逻辑（进程）侧", "固定，2 的幂", "程序被切成的块"],
                  ["帧frame", "物理侧", "与页相同", "内存被切成的块"],
                  ["页表page table", "内存里", "随进程大小变", "页号 → 帧号"]],
                 ["22%", "24%", "22%", "32%"]),
                ("code", "c", "/* 拆分与拼装：位运算版（页大小 2^n） */\n#define PAGE_SIZE 4096          /* 2^12 */\nunsigned page_no(unsigned long addr) { return addr >> 12; }      /* 高位 = 页号 */\nunsigned offset (unsigned long addr) { return addr & (PAGE_SIZE - 1); }  /* 低位 = 偏移 */\nunsigned long build(unsigned frame, unsigned off) {\n    return ((unsigned long)frame << 12) | off;   /* 拼回物理地址 */\n}\n/* 课件 p.30：Linux 上 getconf PAGESIZE 就是看这个 2^n */", "课件 p.29–p.34；页与帧大小相同，所以偏移原样保留"),
                ("eg", "页大小 4 字节（n = 2）、逻辑空间 16 字节（m = 4）。页 0 映射到帧 5。问：逻辑地址 24 的物理地址是多少？",
                 ["逻辑地址 24 = 二进制 11000 → 页号 p = 高 2 位 = 0，偏移 d = 低 3 位 = 110(=6)",
                  "页 0 → 帧 5，所以物理页框从帧 5 开始",
                  "物理地址 = 帧号 101 后接偏移 110 → 10110 = 22"],
                 "答案：22（课件 p.34 的例子）。记法：<b>换号不换内位移</b>——页号换成帧号，偏移原样抄下去。"),
            ],
        },
        {
            "no": "8", "zh": "地址翻译与 TLB：EAT 怎么算", "en": "TLB and EAT",
            "lec": "分页的核心动作是查表换号，问题是每次访问都要多读一次内存。TLB 就是为此存在的缓存。这节的 EAT 公式必须会用——课件给了两个命中率，算出来是 120ns 与 101ns。",
            "body": [
                ("svg", _PG, "图 3　分页翻译：页号查表换帧号，偏移原样保留；未命中 TLB 要多访存一次"),
                ("eq", "EAT = (e + m) × a + (e + 2m) × (1 − a)"),
                ("table_sym", [("width:16%", "符号"), ("width:46%", "读法·含义"), ("width:38%", "单位")],
                 [["EAT", "有效访问时间（effective access time）", "纳秒（ns）"],
                  ["e", "TLB 查找时间（associative lookup）", "纳秒（ns）"],
                  ["m", "一次内存访问时间（memory access time）", "纳秒（ns）"],
                  ["a", "TLB 命中率（hit ratio）", "无量纲，0–1"]]),
                ("eg", "m = 100ns、e 忽略。命中率 a = 80% 与 a = 99% 时 EAT 各是多少？说明为什么 99% 很关键。",
                 ["a = 0.8：0.8×100 + 0.2×200 = 120ns（慢了 20%）",
                  "a = 0.99：0.99×100 + 0.01×200 = 101ns（只慢 1%）",
                  "因为未命中要 2m：先查页表再一次取数据"],
                 "答案：120ns 与 101ns（课件 p.41）。一句话：<b>命中率差 1%，EAT 差 1ns 级的稳定开销</b>，所以 TLB 只有几十项也要做。"),
            ],
        },
        {
            "no": "9", "zh": "保护位与共享页", "en": "Protection and Sharing",
            "lec": "页表不只是地址映射表，它还兼职门禁：每帧带保护位（只读/可写），每项带有效位（在不在这个进程的地址空间里）。共享页解释了 L08 说的「代码可以多进程共用一份」。",
            "body": [
                ("code", "c", "/* 页表项里到底有什么（示意） */\ntypedef struct {\n    unsigned frame  : 20;   /* 帧号 */\n    unsigned valid  : 1;    /* 1 = 在本进程地址空间里，0 = 非法 */\n    unsigned writable : 1;  /* 0 = 只读（代码与常量页） */\n    unsigned exec   : 1;    /* 可执行 */\n} pte_t;\n\n/* 命中 valid=0 的页 → trap；命中只读页却要写 → trap */", "课件 p.42；违规一律 trap 到内核，进程收到段错误"),
                ("p", "课件 p.43 的例子：14 位地址空间（0–16383）、程序只用到 10468 字节、页大小 2KB——于是 11 位偏移、3 位页号；最后用到的页号是 10468/2048 = 5.11 取整为第 5 页，页表里 6 以后的项全标 invalid。"),
                ("eg", "接上例：进程 72766 字节、页大小 2048 字节。问：需要几页？最后一页用了多少字节、内部碎片多少？",
                 ["72766 ÷ 2048 = 35 余 1086 → 需要 36 页（35 整页 + 1 个不满页）",
                  "最后一页只用 1086 字节",
                  "内部碎片 = 2048 − 1086 = 962 字节"],
                 "答案：36 页、碎片 962 字节（课件 p.46）。这也是 §10 讨论「页大小为什么不能太小也不能太大」的由来。"),
            ],
        },
        {
            "no": "10", "zh": "页大小怎么定：两头相加求最小", "en": "Optimal Page Size",
            "lec": "页大小不是随便定的：页小则内部碎片少但页表变大，页大则反过来。课件用一个成本模型把两头加起来求极小值，得到 p = √(2se)——这就是「为什么真实系统用 4KB」的答案雏形。",
            "body": [
                ("eq", "总开销 = s·e / p + p / 2   →   最优页大小 p = √(2·s·e)"),
                ("table_sym", [("width:18%", "符号"), ("width:46%", "读法·含义"), ("width:36%", "单位")],
                 [["s", "平均进程大小（average process size）", "字节"],
                  ["p", "页大小（page size）", "字节"],
                  ["e", "页表每项大小（entry size）", "字节"],
                  ["s·e/p", "页表开销：页数 × 每项大小", "字节"],
                  ["p/2", "内部碎片：平均浪费半页", "字节"]]),
                ("code", "c", "/* 按模型算最优页大小：p = sqrt(2*s*e) */\n#include <math.h>\n#include <stdio.h>\nint main(void) {\n    double s = 128 * 1024;   /* 平均进程 128KB */\n    double e = 8;            /* 页表项 8 字节 */\n    printf(\"最优页大小 = %.0f 字节\\n\", sqrt(2 * s * e));\n    return 0;\n}\n/* 输出 1448 —— 工程上取 2 的幂：1K / 2K / 4K */", "课件 p.47–p.48；求导得 p² = 2se"),
                ("eg", "代入 s = 128KB、e = 8 字节，算出最优页大小；为什么真实系统不用这个数？",
                 ["p = √(2 × 131072 × 8) = √2097152 ≈ 1448 字节",
                  "但页大小必须是 2 的幂：取 1K 或 2K 更实际",
                  "现代 x86-64 用 4KB，还提供 2MB / 1GB 大页给需要大块连续访问的场景"],
                 "答案：约 1448 字节（估），工程上取 2 的幂（课件 p.47–p.48）。一句话：<b>模型给方向，实现要凑 2 的幂</b>。"),
            ],
        },
        {
            "no": "11", "zh": "页表太大怎么办：多级与反置", "en": "Huge Page Tables",
            "lec": "页表自己也会成为大问题：32 位 + 4KB 页，一个进程就要 100 万项、约 4MB，500 个进程就是 2GB，而且页表还不能被换出去。这节给三条出路，各有代价。",
            "body": [
                ("svg", _MULTI, "图 4　两级页表：p1 索引外层、p2 是内层页表内的偏移；只有用到的内层页表才占内存"),
                ("p", "课件 p.49 把账算清：32 位地址空间 + 4KB 页 → 2^32 / 2^12 = 100 万项；每项 4 字节 → 光页表 4MB；每个程序一份，500 个程序就是 2000MB；而且页表不能换出（换出去就没法访问内存）。"),
                ("p", "课件 p.50–p.53 讲多级页表：把页表本身也分页，外层索引内层；课件 p.56–p.58 把它推到 64 位——4KB 页、52 位页号，按 10 位一级要 7 级，慢到不可接受。p.59–p.61 给另一条路：反置页表（inverted page table），按物理帧建表，省内存但查找更慢、共享页困难。"),
                ("eg", "32 位机器、页大小 1KB、页表项 4 字节。问：单张页表多大？切成两级后外层多少项？",
                 ["页大小 1KB = 2^10 → 页内偏移 10 位，页号 22 位 → 页表项数 2^22 = 4 194 304",
                  "单张页表 = 4 194 304 × 4 字节 = 16MB（每个进程都要一份）",
                  "两级时页号切成 12 位 + 10 位：外层 2^12 = 4096 项，内层每张 2^10 = 1024 项"],
                 "答案：16MB；外层 4096 项（课件 p.53 的算例）。省的不是「总项数」，而是<b>真正常驻的那部分</b>。"),
            ],
        },
        {
            "no": "12", "zh": "交换与切换时间", "en": "Swapping",
            "lec": "内存不够怎么办？把整个进程搬到磁盘上（换出），需要时再搬回来（换入）。这节的重点不是概念，而是那道算例：100MB 来回一趟要 4 秒。看到这个数字，就明白现代系统为什么不做标准交换。",
            "body": [
                ("q", "A process must be in memory to be executed. A process can be swapped temporarily out of memory to a backing store, and then brought back into memory for continued execution.", "课件 p.62"),
                ("code", "bash", "# 交换时间的量级估算（与课件 p.64 同口径）\n# 进程 100MB，磁盘 50MB/s：换出 100/50 = 2s，换入再 2s，共 4s\n# 若内存压力只是「少了几个页」，就不该整进程换 —— 只换真正在用的部分\nfree -m          # 看本机内存与换页情况\nvmstat 1         # si/so 两列就是换入与换出的速率", "课件 p.62–p.65；量级用除法就能估"),
                ("p", "课件 p.62 讲配套概念：后备存储（backing store）要够快够大，能装下所有用户的全部内存镜像；交换时间的主要部分是传输时间，与交换的内存量成正比；系统维护「镜像在磁盘上」的就绪队列。p.65 的结论：标准交换在现代 OS 里已不用，只在空闲内存极低时才做变种。"),
                ("eg", "进程 100MB、磁盘 50MB/s。换出要多久？若只换出其中 10MB 又要多久？差别说明了什么？",
                 ["100 ÷ 50 = 2 秒，换出；换入再 2 秒 → 一次切换约 4 秒",
                  "只换 10MB：10 ÷ 50 = 0.2 秒 ×2 = 0.4 秒",
                  "差 10 倍：所以「少换、只换在用的部分」是唯一可行的方向"],
                 "答案：约 4 秒与约 0.4 秒（课件 p.64）。判据一句话：<b>交换代价与数据量成正比，不是常数</b>。"),
            ],
        },
        {
            "no": "13", "zh": "真实芯片：IA-32、x86-64 与 ARM", "en": "Real Architectures",
            "lec": "最后一节把概念落到三块真实芯片上：IA-32 同时支持分段与分页，x86-64 用四级页表，ARM 用两级 TLB。不要求背参数，只要求你能对上「哪套机制在哪块芯片上」。",
            "body": [
                ("table", ["芯片", "分段", "分页", "页大小", "页表层数"],
                 [["IA-32", "支持，每段可到 4GB", "支持（可叠加）", "4KB / 4MB", "两级（页目录 + 页表）"],
                  ["x86-64", "基本不用（平坦模型）", "支持", "4KB / 2MB / 1GB", "四级"],
                  ["ARM", "少量（域/权限）", "支持", "4KB / 16KB / 1MB 段", "一级页表 + 两级 TLB"]],
                 ["14%", "22%", "16%", "22%", "26%"]),
                ("p", "课件 p.68–p.69 讲 IA-32：段可到 4GB、每进程最多 16K 段（前 8K 私有 LDT、后 8K 共享 GDT）；CPU 先由分段单元产生线性地址，再由分页单元产生物理地址，两者合起来就是 MMU。p.72 讲 PAE：分页升三级、项升到 64 位。"),
                ("eg", "x86-64 有 64 位寄存器，但为什么实际只用 48 位地址？多级页表在这里付出什么代价？",
                 ["64 位地址全用会让页表层数与表项爆炸（52 位页号要 7 级间接）",
                  "所以只实现 48 位（后续扩展到 52 位），四级页表够用",
                  "代价：一次翻译最多 4 次访存，全靠 TLB 命中把它摊平"],
                 "答案：因为页表规模与访问次数都扛不住（课件 p.56–p.58、p.73）。一句话：<b>地址位宽不是越大越好，它要跟页表机制一起定</b>。"),
            ],
        },
    ],

    "summary": {
        "no": "14", "zh": "本讲小结", "en": "Takeaways",
        "lec": "收口用一张表：每行配一个能算的动作。",
        "head": ["记住什么", "一句话", "怎么自查"],
        "head_widths": ["22%", "52%", "26%"],
        "rows": [
            ["base / limit", "limit 是长度，上界要减 1", "算 §1 那道合法区间"],
            ["逻辑 / 物理", "程序只见逻辑地址，MMU 换号", "说清搬家后逻辑地址为什么不变"],
            ["三种方案", "连续要整块 / 分段按逻辑 / 分页按固定", "判 §3 那道 12KB"],
            ["三算法", "first 快、best 慢、worst 最差", "走 §4 那道洞分配"],
            ["碎片", "外部在之间、内部在里面", "判那个 2KB×3 的例子"],
            ["分段", "s < STLR 且 d < 段长", "算 translate(2,1200)"],
            ["分页", "页换帧，偏移不变", "算 24 → 22 那道"],
            ["EAT", "(e+m)a + (e+2m)(1−a)", "算 80% 与 99%"],
            ["页大小", "p = √(2se)，工程取 2 的幂", "算 1448 那道"],
            ["多级页表", "省的是常驻部分", "算外层 4096 项"],
            ["交换", "代价与数据量成正比", "算 4 秒与 0.4 秒"],
        ],
        "tail": "一句话收口：<b>连续分配要整块，分段按逻辑切，分页按固定大小切</b>——越往后越灵活，代价是页表与访存次数。",
    },

    "quiz": {
        "no": "15", "zh": "自测", "en": "Self-check",
        "lec": "六题只用本讲内容：前两题判保护与地址，后四题判分配、分页与取舍。",
        "items": [
            ("base = 300040、limit = 120900 时，合法地址范围是什么？",
             "答：300040 到 300040 + 120900 − 1 = 420939（课件 p.4）。回看 §1。"),
            ("逻辑地址与物理地址的区别是什么？谁来做换算？",
             "答：逻辑地址由 CPU 生成（也叫虚拟地址），物理地址是内存单元看到的；换算由 MMU 完成（课件 p.6–p.7）。回看 §2。"),
            ("外部碎片与内部碎片分别出现在哪类方案里？",
             "答：外部碎片出现在连续分配与分段；内部碎片主要在分页（最后一页填不满）（课件 p.18、p.29）。回看 §5、§7。"),
            ("页大小 4 字节、逻辑空间 16 字节、页 0 映射帧 5，逻辑地址 24 的物理地址是多少？",
             "答：页号 0、偏移 6 → 帧 5 → 物理地址 10110 = 22（课件 p.34）。回看 §7。"),
            ("TLB 命中率 90%、m = 100ns、e 忽略时 EAT 是多少？",
             "答：0.9×100 + 0.1×200 = 110ns（按课件 p.41 的公式算）。回看 §8。"),
            ("为什么现代系统不再做「标准交换」？",
             "答：换出换入太慢（100MB 在 50MB/s 上往返约 4 秒），只在空闲内存极低时做变种交换（课件 p.64–p.65）。回看 §12。"),
        ],
    },

    "glossary": {
        "no": "16", "zh": "术语表", "en": "Glossary",
        "lec": "本讲术语按首次出现排；英文是课件原词，查文档与做题都用它。",
        "rows": [
            ("基址寄存器", "base register", "课件 p.4", "最小合法物理地址"),
            ("限长寄存器", "limit register", "课件 p.4", "地址范围的长度（不是最大地址）"),
            ("逻辑地址", "logical address", "课件 p.6", "CPU 生成的地址，也叫虚拟地址"),
            ("物理地址", "physical address", "课件 p.6", "内存单元看到的地址"),
            ("内存管理单元", "MMU", "课件 p.7", "虚拟到物理的映射硬件"),
            ("重定位寄存器", "relocation register", "课件 p.8", "运行时加到每个地址上的基址"),
            ("连续分配", "contiguous allocation", "课件 p.12", "整块装入"),
            ("固定分区", "fixed-sized partition", "课件 p.14", "预切好分区，进程数被锁死"),
            ("可变分区", "variable partition", "课件 p.15", "按需切分，可合并相邻空闲区"),
            ("洞", "hole", "课件 p.15", "空闲内存块"),
            ("首次适配", "first-fit", "课件 p.16", "第一个够大的洞"),
            ("最佳适配", "best-fit", "课件 p.16", "最小的够大的洞"),
            ("最差适配", "worst-fit", "课件 p.16", "最大的洞，利用率最差"),
            ("外部碎片", "external fragmentation", "课件 p.18", "洞太小用不上"),
            ("内部碎片", "internal fragmentation", "课件 p.18", "分区内多给的"),
            ("紧凑", "compaction", "课件 p.19", "把空闲区挪到一起，需动态重定位"),
            ("分段", "segmentation", "课件 p.20", "按逻辑切段"),
            ("段表", "segment table", "课件 p.23", "段号到基址、长度与权限"),
            ("分页", "paging", "课件 p.28", "切成固定大小的页"),
            ("帧", "frame", "课件 p.29", "物理侧的固定块"),
            ("页表", "page table", "课件 p.31", "页号到帧号"),
            ("翻译后备缓冲器", "TLB", "课件 p.36", "页表的缓存，只有几十到几千项"),
            ("有效访问时间", "EAT", "课件 p.41", "带命中率的平均访问时间"),
            ("反置页表", "inverted page table", "课件 p.59", "按物理帧建表"),
            ("交换", "swapping", "课件 p.62", "换出换入整个进程"),
            ("后备存储", "backing store", "课件 p.62", "存放换出进程的磁盘"),
        ],
    },

    "appendix": {
        "no": "17", "zh": "附录", "en": "Appendix",
        "lec": "一张符号速查加一组误解。速查那几条做题时直接用。",
        "symbols": [
            ("p / d", "页号 / 页偏移", "课件 p.31"),
            ("m / n", "逻辑地址位数 / 页大小位数", "课件 p.31"),
            ("PTBR / PTLR", "页表基址 / 页表长度寄存器", "课件 p.36"),
            ("STBR / STLR", "段表基址 / 段表长度寄存器", "课件 p.23"),
            ("EAT", "有效访问时间", "课件 p.41"),
            ("a / m / e", "命中率 / 内存访问时间 / TLB 查找时间", "课件 p.41"),
            ("LDT / GDT", "局部 / 全局描述符表（IA-32）", "课件 p.68"),
            ("PAE", "页地址扩展（page address extension）", "课件 p.72"),
        ],
        "myths_title": "常见误解",
        "myths": [
            "把 limit 当最大地址：它是长度，最大合法地址是 base + limit − 1。",
            "以为 best-fit 一定最优：它搜索最慢，课件说 first 与 best 都优于 worst。",
            "以为分页没有碎片：有内部碎片，最后一页平均浪费半页。",
            "以为 64 位系统用满 64 位地址：x86-64 实际只用 48 位。",
            "以为交换很快：100MB 在 50MB/s 上往返就是 4 秒。",
        ],
    },

    "tail": [],
}
