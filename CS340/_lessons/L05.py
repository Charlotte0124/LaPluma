# -*- coding: utf-8 -*-
"""L05 进程间通信与同步 · 练习型讲义（代码 + 例题运算 + 结构图为主）。

来源：课件 L05_IPCandProcessSynchronization.pdf（148 页）。结构图按课件概念自绘；
引文 ('q', …, '课件 p.N') 均为课件原文短语。代码块里的生产者-消费者代码取自课件 p.95 版式，
并补了可编译的 POSIX 写法，便于课堂直接跑。
"""

_IPC = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="14" y="18" width="120" height="46" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="74" y="46" text-anchor="middle" fill="#F4F1E6" font-size="12">进程 A</text>
  <rect x="486" y="18" width="120" height="46" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="546" y="46" text-anchor="middle" fill="#F4F1E6" font-size="12">进程 B</text>
  <rect x="196" y="10" width="228" height="28" fill="#1C1B13" stroke="#E7C246"/>
  <text x="310" y="29" text-anchor="middle" fill="#E7C246" font-size="11">① 管道 pipe（单向字节流）</text>
  <rect x="160" y="60" width="300" height="28" fill="#161614" stroke="#2A2A24"/>
  <text x="310" y="79" text-anchor="middle" fill="#F4F1E6" font-size="11">② 共享内存（最快，但要自己加锁）</text>
  <rect x="182" y="110" width="256" height="28" fill="#161614" stroke="#2A2A24"/>
  <text x="310" y="129" text-anchor="middle" fill="#F4F1E6" font-size="11">③ 消息队列 / 套接字（内核代管）</text>
  <path d="M134 41 L192 26" stroke="#8FA7B8" stroke-width="1.1"/>
  <path d="M134 76 L156 76" stroke="#8FA7B8" stroke-width="1.1"/>
  <path d="M134 124 L178 124" stroke="#8FA7B8" stroke-width="1.1"/>
</svg>"""

_RACE = """<svg viewBox="0 0 620 170" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="18" fill="#A8A498" font-size="11">正确（串行）</text>
  <rect x="14" y="26" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="59" y="41" text-anchor="middle" fill="#F4F1E6" font-size="10">A 读 0</text>
  <rect x="110" y="26" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="155" y="41" text-anchor="middle" fill="#F4F1E6" font-size="10">A 写 1</text>
  <rect x="206" y="26" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="251" y="41" text-anchor="middle" fill="#F4F1E6" font-size="10">B 读 1</text>
  <rect x="302" y="26" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="347" y="41" text-anchor="middle" fill="#F4F1E6" font-size="10">B 写 2</text>
  <text x="404" y="42" fill="#E7C246" font-size="11">结果 2 ✓</text>
  <text x="14" y="86" fill="#A8A498" font-size="11">竞争（交错）</text>
  <rect x="14" y="94" width="90" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="59" y="109" text-anchor="middle" fill="#E7C246" font-size="10">A 读 0</text>
  <rect x="110" y="94" width="90" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="155" y="109" text-anchor="middle" fill="#E7C246" font-size="10">B 读 0</text>
  <rect x="206" y="94" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="251" y="109" text-anchor="middle" fill="#F4F1E6" font-size="10">A 写 1</text>
  <rect x="302" y="94" width="90" height="22" fill="#161614" stroke="#2A2A24"/><text x="347" y="109" text-anchor="middle" fill="#F4F1E6" font-size="10">B 写 1</text>
  <text x="404" y="110" fill="#E6392F" font-size="11">结果 1 ✗ 丢一次更新</text>
  <path d="M59 66 L59 92" stroke="#6E6B61" stroke-width="1" stroke-dasharray="3 3"/>
  <path d="M155 66 L155 92" stroke="#6E6B61" stroke-width="1" stroke-dasharray="3 3"/>
</svg>"""

_SEM = """<svg viewBox="0 0 620 160" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="24" y="60" width="150" height="44" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="99" y="87" text-anchor="middle" fill="#F4F1E6" font-size="12">进程调 down()</text>
  <rect x="240" y="18" width="150" height="36" fill="#1C1B13" stroke="#E7C246"/>
  <text x="315" y="41" text-anchor="middle" fill="#E7C246" font-size="11">s &gt; 0 → s = s−1 进入</text>
  <rect x="240" y="108" width="150" height="36" fill="#161614" stroke="#2A2A24"/>
  <text x="315" y="131" text-anchor="middle" fill="#F4F1E6" font-size="11">s = 0 → 睡眠排队</text>
  <rect x="452" y="60" width="140" height="44" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="522" y="87" text-anchor="middle" fill="#F4F1E6" font-size="12">另一进程 up()</text>
  <path d="M174 78 L236 38" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#s1)"/>
  <path d="M174 86 L236 124" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#s1)"/>
  <path d="M392 126 C430 150 470 120 452 92" stroke="#E7C246" stroke-width="1.2" fill="none" marker-end="url(#s2)"/>
  <text x="404" y="150" fill="#6E6B61" font-size="9">up 唤醒一个等待者</text>
  <defs>
    <marker id="s1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker>
    <marker id="s2" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker>
  </defs>
</svg>"""

_RING = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="60" y="46" width="60" height="34" fill="#1C1B13" stroke="#E7C246"/>
  <rect x="120" y="46" width="60" height="34" fill="#1C1B13" stroke="#E7C246"/>
  <rect x="180" y="46" width="60" height="34" fill="#161614" stroke="#2A2A24"/>
  <rect x="240" y="46" width="60" height="34" fill="#161614" stroke="#2A2A24"/>
  <rect x="300" y="46" width="60" height="34" fill="#161614" stroke="#2A2A24"/>
  <rect x="360" y="46" width="60" height="34" fill="#161614" stroke="#2A2A24"/>
  <text x="90" y="68" text-anchor="middle" fill="#E7C246" font-size="10">item</text>
  <text x="150" y="68" text-anchor="middle" fill="#E7C246" font-size="10">item</text>
  <text x="210" y="68" text-anchor="middle" fill="#6E6B61" font-size="10">空</text>
  <text x="270" y="68" text-anchor="middle" fill="#6E6B61" font-size="10">空</text>
  <text x="330" y="68" text-anchor="middle" fill="#6E6B61" font-size="10">空</text>
  <text x="390" y="68" text-anchor="middle" fill="#6E6B61" font-size="10">空</text>
  <text x="60" y="36" fill="#A8A498" font-size="10">head（消费者取）</text>
  <text x="350" y="36" fill="#A8A498" font-size="10">tail（生产者放）</text>
  <text x="86" y="104" fill="#6E6B61" font-size="10">↑</text>
  <text x="376" y="104" fill="#6E6B61" font-size="10">↑</text>
  <text x="60" y="128" fill="#A8A498" font-size="10">empty = 4，full = 2，mutex = 1（N = 6 的示意）</text>
</svg>"""

LESSON = {
    "code": "CS340",
    "no": "L05",
    "zh": "进程间通信与同步",
    "en": "IPC and Process Synchronization",
    "out": "L05_进程间通信与同步_讲义.pdf",
    "sub": "讲义 · 练习型 ｜ 代码 + 例题运算 + 结构图 ｜ 每个经典问题都能自己推一遍信号量的值",
    "meta": [
        ("源课件", "L05_IPCandProcessSynchronization.pdf，148 页（Xuan Xie，MUST；素材由 Prof. Subrota Kumar Mondal 提供）"),
        ("本讲口径", "以代码与推演为主：每节至少一段可跑代码或一道带数的例题，理论只解释为什么这么写"),
        ("页码口径", "「课件 p.N」指源 PDF 的页序（共 148 页），不是幻灯片编号"),
        ("怎么读", "§1 三种做法 → §2 管道 → §3 竞争条件 → §4 临界区四条 → §5 信号量 PV → §6 生产者消费者 → §7 哲学家与读者写者"),
        ("动手指令", "Linux / WSL 下 `gcc -pthread` 直接跑；§3 的竞争条件程序跑 5 次会看到不同的错误值"),
        ("原文在哪", "CS340\\01_讲义\\L05_IPCandProcessSynchronization.pdf；本讲义只讲，不复制全文"),
    ],

    "sections": [
        {
            "no": "0", "zh": "本讲导读", "en": "How to Use This Handout",
            "lec": "这讲是整门课最该动手的一讲：所有结论都能用一段 C 代码跑出来，或用一次 PV 推演算出来。理论只有一句——并发访问共享数据必须互斥。",
            "body": [
                ("p", "<b>这一节能解决什么。</b>两个具体问题：① 两个进程同时改一个变量，为什么结果会少一点；② 写一个「生产者放、消费者取」的缓冲，怎样保证不覆盖、不空取、不饿死。"),
                ("p", "<b>这一节不能解决什么。</b>不涉及分布式锁与网络同步；本讲的信号量只在单机内核里有效，跨机器要靠别的机制。"),
                ("p", "<b>每节都有一道能算的题</b>：信号量当前值是多少、缓冲区里有几个、哪个进程在睡——算不出来就是没懂，别跳过。"),
                ("note", "本讲地图", "三种 IPC（§1）→ 管道代码（§2）→ 竞争条件与丢更新（§3）→ 四条硬要求（§4）→ PV 推演（§5）→ 生产者消费者（§6）→ 哲学家死锁（§7）。"),
            ],
        },
        {
            "no": "1", "zh": "IPC 的三种做法", "en": "Three Ways to Communicate",
            "lec": "先把「通道」画清楚，再记住每种通道的代价：管道最省事、共享内存最快、消息队列最省心。这节配一张结构图就够。",
            "body": [
                ("svg", _IPC, "图 1　三种 IPC 通道：管道（字节流）/ 共享内存（最快但需自己加锁）/ 消息队列（内核代管）"),
                ("q", "As a matter of fact, using pipe is one of ways for processes to communicate.", "课件 p.5"),
                ("code", "bash", "# 管道：shell 里的竖线就是一个 pipe\nls -l | wc -l          # 左边进程的标准输出接右边进程的标准输入\n\n# 共享内存：速度最快，但要自己加锁（没有锁就会出 §3 的竞争条件）\n", "管道由内核维护，你只负责接两头"),
                ("table", ["做法", "数据怎么走", "谁保证互斥", "代价"],
                 [["管道 pipe", "单向字节流，先进先出", "内核保证读写不越界", "只适合线性流水，双向要两根"],
                  ["共享内存", "两块虚拟内存指向同一物理页", "<b>没人保证，要你自己加锁</b>", "最快，但最容易写错"],
                  ["消息队列", "内核里排队，收发各一次系统调用", "内核保证", "每次收发都要跨界，最慢"]],
                 ["16%", "34%", "26%", "24%"]),
                ("eg", "两个进程要双向通信（各写各读），最少要几根管道？为什么？",
                 ["一根管道只有一个方向：写端到读端",
                  "要让两边同时写，就得有两根：A→B 一根、B→A 一根",
                  "还要在 fork 后关掉各自不用的那一端，否则读到 EOF 会永远等不到"],
                 "答案：两根。课件 p.8 给的就是这个六步做法：建两根 → fork → 父关要读的一端、子关要写的一端。"),
            ],
        },
        {
            "no": "2", "zh": "竞争条件：为什么 count 会少一", "en": "Race Condition",
            "lec": "这节必须自己跑一遍。程序会稳定地给出小于 200000 的结果——不是编译器坏了，是「读-加-写」三步被切开了。",
            "body": [
                ("code", "c", "/* race.c —— 两个进程各把共享变量加 10 万次 */\n#include <stdio.h>\n#include <sys/mman.h>\n#include <sys/wait.h>\n#include <unistd.h>\n\nint main(void) {\n    int *count = mmap(NULL, sizeof(int), PROT_READ|PROT_WRITE,\n                      MAP_SHARED|MAP_ANONYMOUS, -1, 0);\n    *count = 0;\n    if (fork() == 0) {                       /* 子进程 */\n        for (int i = 0; i < 100000; i++) (*count)++;\n        _exit(0);\n    }\n    for (int i = 0; i < 100000; i++) (*count)++;   /* 父进程 */\n    wait(NULL);\n    printf(\"count = %d（期望 200000）\\n\", *count);\n    return 0;\n}\n/* gcc race.c -o race && ./race   —— 多跑几次，结果常常不到 200000 */", "跑五次，记下每次的数字，这就是竞争条件的证据"),
                ("svg", _RACE, "图 2　同一个 ++ 在两种执行顺序下的结果：串行得 2，交错得 1"),
                ("p", "`(*count)++` 在机器上至少三条指令：读进寄存器、加一、写回内存。两条路径一旦在「读」之后、「写」之前交错，后写的那次就把前一次的结果盖掉——这叫<b>丢失更新</b>（lost update）。课件 p.44 把这类「结果取决于调度时机」的毛病统一叫<b>竞争条件</b>（race condition）。"),
                ("eg", "初值 count = 0，A、B 各执行一次 `count++`。列出三种可能的交错与最终值。",
                 ["① 完全串行：A 读 0 → A 写 1 → B 读 1 → B 写 2 → 结果 2",
                  "② A 读完被切走，B 读 0 → A 写 1 → B 写 1 → 结果 1（丢一次）",
                  "③ B 先读 0，A 写 1，B 写 1 → 结果仍为 1（同样丢一次）"],
                 "答案：结果可能是 2 或 1。<b>只要交错发生在「读」与「写」之间，就丢一次更新</b>；这就是为什么单次加法看着没错、循环十万次就明显少。"),
                ("eg", "两个进程各加 10 万次，实测 13 万–17 万之间浮动。用上面的模型解释「为什么不是固定值」。",
                 ["每次交错丢更新的次数取决于调度时机，而调度由内核决定，不可预测",
                  "循环次数越多，可交错的点越多，丢失次数越多",
                  "所以结果是一个分布，不是固定值"],
                 "答案：因为交错的次数由调度器决定。这恰好说明竞争条件是「不确定的正确性」，不能靠运气，只能靠互斥。"),
            ],
        },
        {
            "no": "3", "zh": "临界区：四条硬要求怎么用", "en": "Critical Section Requirements",
            "lec": "四条要求不是背书，是判据：拿任何一个「互斥方案」来，逐条问它过不过。用一道题练这个判据。",
            "body": [
                ("p", "课件 p.44–p.45 定义：临界区（critical section）是<b>访问共享对象的代码段</b>；入口要声明「我开始用」，出口要声明「我用完了」。注意它是代码段，不是共享对象本身。"),
                ("table", ["要求", "课件原文（p.50–p.51）", "违反了会怎样"],
                 [["① 互斥", "No two processes can be simultaneously inside their critical sections", "两个进程同时改，丢更新"],
                  ["② 不假设速度与 CPU 数", "No assumptions can be made about the speeds and the numbers of CPUs", "在单核能跑、多核就崩"],
                  ["③ 区外不许阻塞别人", "No process running outside its critical region can cause other processes to be blocked", "全班都堵住，没人能进"],
                  ["④ 不许无限等待", "No process has to wait forever in order to enter its critical region", "饿死（starvation）"]],
                 ["14%", "56%", "30%"]),
                ("code", "c", "/* 用「严格轮换」当反例：两个进程必须交替进临界区 */\nturn = 0;                 /* 0 表示轮到 A，1 表示轮到 B */\n\n/* 进程 A */                    /* 进程 B */\nwhile (turn != 0) ;             while (turn != 1) ;\ncritical_section();             critical_section();\nturn = 1;                       turn = 0;\n\n/* 问题：A 跑完一次后如果不再进，B 也得等 A 把 turn 交出来吗？\n   —— 是的，这违反要求 ③：区外的 A 把 B 堵住了。 */", "课件 p.86 的对比表把「严格轮换」判成 Yes and No 就是这个原因"),
                ("eg", "判断：严格轮换违反了哪一条？如果 A 在临界区里挂了（不再执行），B 会怎样？",
                 ["违反要求 ③：A 在临界区外（跑完了，不再进来）却让 B 无限等待",
                  "A 一旦挂掉，B 永远等 turn 变成 1 → 也违反要求 ④（无限等待）"],
                 "答案：同时踩 ③ 和 ④。所以课件把它标成「Yes and No」——互斥是有的，但可用性不合格。"),
            ],
        },
        {
            "no": "4", "zh": "信号量：PV 怎么推", "en": "Semaphore and PV",
            "lec": "这节是全讲的工具。只要会推 s 值，后面三个经典问题都是同一套算术：down 前先看 s 是不是 0。",
            "body": [
                ("code", "c", "/* 课件 p.78 的原版伪代码：down / up 都是原子操作 */\nvoid down(semaphore *s) {\n    if (*s > 0) *s = *s - 1;\n    else        sleep();          /* 值为 0 就睡，醒来后重试 */\n}\n\nvoid up(semaphore *s) {\n    if (*s == 0) wakeup_proc();   /* 有人睡着就叫醒一个 */\n    *s = *s + 1;\n}", "原子 = 中间不会被切换；只有 sleep 那一刻算「暂停并重试」"),
                ("svg", _SEM, "图 3　down / up 的两条路径：s>0 直接进，s=0 睡排队；up 负责叫醒一个并让 s 加 1"),
                ("p", "初值决定身份：初值 1 = <b>二元信号量</b>（当锁用）；初值 N = <b>计数信号量</b>（当「还剩几个空位」用）。这一个区别后面两节都会用到。"),
                ("eg", "s 初值 1。进程 A、B 依次执行：A.down → B.down → A.up → B 醒来重试 down。逐步写出 s 的值和谁在睡。",
                 ["A.down：s = 1 > 0 → s = 0，A 进临界区",
                  "B.down：s = 0 → B 睡眠排队",
                  "A.up：有人在睡 → 唤醒 B；s = 0 + 1 = 1",
                  "B 醒来重试 down：s = 1 > 0 → s = 0，B 进临界区"],
                 "答案：结束时 s = 0，B 在临界区里。注意 up 的顺序是「先唤醒、再加一」，否则被唤醒的进程会看到 s 仍是 0 而再次睡下。"),
                ("eg", "若把 up 写成「先加一再唤醒」，上面第 3 步会发生什么？",
                 ["s = 0 + 1 = 1，然后唤醒 B",
                  "B 醒来 down：s = 1 > 0 → s = 0，能进 —— 这次侥幸没错",
                  "但若此时还有第三个进程 C 抢在 B 之前 down，C 拿到 s=0，B 又睡回去"],
                 "答案：看起来仍能跑，但在竞争更激烈时会多一次无谓的睡眠/唤醒，甚至在「唤醒又立即被抢」下造成饿死。课件 p.78 的顺序不是随意写的。"),
            ],
        },
        {
            "no": "5", "zh": "生产者-消费者：算空位、算满位", "en": "Producer-Consumer",
            "lec": "这节只做两件事：读懂课件那三行 down/up 的顺序，然后算出一个具体状态下三个信号量各是多少。算得出来，题目就不会错。",
            "body": [
                ("code", "c", "/* 课件 p.95 原版（N = 100，缓冲中最多 100 个） */\n#define N 100\ntypedef int semaphore;\nsemaphore mutex = 1;      /* 互斥：同一时刻只有一个在动缓冲区 */\nsemaphore empty = N;      /* 空位数，初值 N */\nsemaphore full  = 0;      /* 已放数，初值 0 */\n\nvoid producer(void) {          /* 生产者 */\n    int item;\n    while (TRUE) {\n        item = produce_item();\n        down(&empty);          /* 先问「还有空位吗」 */\n        down(&mutex);          /* 再拿锁 */\n        insert_item(item);\n        up(&mutex);            /* 先放锁 */\n        up(&full);             /* 再报告「多了一个」 */\n    }\n}\n\nvoid consumer(void) {          /* 消费者 */\n    int item;\n    while (TRUE) {\n        down(&full);\n        down(&mutex);\n        item = remove_item();\n        up(&mutex);\n        up(&empty);\n        consume_item(item);\n    }\n}", "课件 p.95；顺序是重点：先 empty/full，后 mutex"),
                ("svg", _RING, "图 4　环形缓冲：head 由消费者推、tail 由生产者推；两把「计数器」盯住空位与实位"),
                ("eg", "N = 100，初始 empty = 100、full = 0、mutex = 1。生产者连续放 3 个、消费者取 1 个之后，三个值各是多少？",
                 ["生产 3 次：每次 down(empty) 减 1、up(full) 加 1 → empty = 97、full = 3",
                  "消费 1 次：down(full) 减 1、up(empty) 加 1 → empty = 98、full = 2",
                  "mutex 每次都 up 回去了 → mutex = 1"],
                 "答案：empty = 98、full = 2、mutex = 1。三者之和恒为 N + 1 = 101，可以用这个等式自查。"),
                ("eg", "缓冲已满（empty = 0）时生产者再调一次 down(&empty) 会怎样？消费者取走一个后谁被唤醒？",
                 ["生产者的 down(&empty) 看到 s = 0 → 睡眠排队，不进入临界区",
                  "消费者取走一个 → up(&empty)：先唤醒等待中的生产者，再 s = 0 + 1 = 1",
                  "生产者被唤醒后重试 down → s = 1 > 0 → s = 0，进临界区插入"],
                 "答案：生产者睡、被消费者唤醒。这也是课件 p.90 说的「requirement #1」：满了要让生产者睡，取走一个就把它叫醒。"),
                ("eg", "如果把两行 down 的顺序写反（先 down(&mutex) 再 down(&empty)），会出什么问题？",
                 ["生产者拿到 mutex 后发现 empty = 0 → 睡在 down(&empty) 里，<b>mutex 没释放</b>",
                  "消费者要取数据必须先拿 mutex，但锁在生产者的手里 → 消费者永远进不去",
                  "两边互相等 = 死锁"],
                 "答案：死锁。规则一句话：<b>先拿「资源计数」、后拿「互斥锁」</b>；反过来就会带着锁睡觉。"),
            ],
        },
        {
            "no": "6", "zh": "哲学家与读者写者：死锁怎么破", "en": "Philosophers and Readers-Writers",
            "lec": "这两道经典题各考一件事：哲学家考「死锁的四个必要条件」，读者写者考「读写比例与公平」。都用信号量算给你看。",
            "body": [
                ("code", "c", "/* 5 个哲学家、5 根叉，每人先拿左手、再拿右手 */\n#define LEFT  (i)\n#define RIGHT ((i + 1) % 5)\n\na = 0; b = 0; c = 0; d = 0; e = 0;   /* 五根叉，1 表示被拿起 */\n\nvoid philosopher(int i) {\n    while (TRUE) {\n        down(&fork[LEFT]);            /* 先拿左手 */\n        down(&fork[RIGHT]);           /* 再拿右手 */\n        eat();\n        up(&fork[LEFT]);\n        up(&fork[RIGHT]);\n        think();\n    }\n}", "死锁版本：五个都先拿左叉"),
                ("p", "五个人同时执行到第一个 down：各自拿到左手的叉，桌上五根叉全被占。接着每个人都调第二个 down —— 等的是别人手里的那根。<b>没人能进 eat()，也没人放手</b>，这就是死锁（课件 p.6 把它列为经典问题，p.86 的对比表也强调同步方案必须避开它）。"),
                ("eg", "上面这版为什么会死锁？给出两种可行的破法，并说明为什么有效。",
                 ["原因：5 人各持 1 把、再等 1 把，形成环（循环等待）",
                  "破法一：只允许 4 人同时上桌（计数信号量初值 4）→ 总有一人能拿到两把，环被打断",
                  "破法二：按奇偶顺序拿（奇数先左后右，偶数先右后左）→ 相邻两人抢叉顺序相反，不会成环"],
                 "答案：两种都有效，因为它们都破坏了「循环等待」这一条。破法三（用一把大锁把整桌锁住）也有效，但把并行度压成 1，代价最大。"),
                ("code", "c", "/* 读者-写者：读者可并发，写者独占 */\nint reader_count = 0;\nsemaphore mutex   = 1;   /* 保护 reader_count */\nsemaphore write   = 1;   /* 写者独占 */\n\nvoid reader(void) {\n    down(&mutex);\n    reader_count++;\n    if (reader_count == 1) down(&write);   /* 第一个读者把写者挡住 */\n    up(&mutex);\n    read_data();\n    down(&mutex);\n    reader_count--;\n    if (reader_count == 0) up(&write);     /* 最后一个读者放开写者 */\n    up(&mutex);\n}", "注意：只有「第一个」和「最后一个」读者碰 write 这个信号量"),
                ("eg", "已有 3 个读者在读时，一个写者来了会怎样？再来 1 个读者呢？",
                 ["写者 down(&write)：write = 0，睡 —— 因为第一个读者已经把它按下去了",
                  "新读者 down(&mutex) → reader_count 3 → 4，不碰 write → 直接进（读读可并发）",
                  "等 4 个读者都读完后，最后一个 down(&mutex) 时把 reader_count 减到 0 → up(&write)，写者才被唤醒"],
                 "答案：写者一直等，新读者不排队。这就是「读者优先」的写法；它的问题是写者可能长期拿不到锁（写者饥饿）。想公平就得再加一个「轮到谁」的信号量。"),
            ],
        },
    ],

    "summary": {
        "no": "7", "zh": "本讲小结", "en": "Takeaways",
        "lec": "收口用一张表：每条都配一个能动手验或能算的动作。",
        "head": ["记住什么", "一句话", "怎么自查"],
        "head_widths": ["22%", "50%", "28%"],
        "rows": [
            ["IPC 三法", "管道省事 / 共享内存最快 / 消息队列最慢但要内核", "画图 1，说出各自代价"],
            ["竞争条件", "读-加-写被打断就丢更新", "跑 race.c，结果 < 200000"],
            ["四条要求", "互斥 / 不假设速度 / 区外不阻塞 / 不饿死", "拿严格轮换逐条判：踩 ③④"],
            ["down/up", "down 见 0 就睡；up 先唤醒再加一", "推 §4 那道 4 步题"],
            ["生产者消费者", "先 down(empty/full)，后 down(mutex)", "算 empty=98 / full=2 那道"],
            ["死锁", "五人各持一把等另一把 = 循环等待", "说出两种破法并说明打断了哪一条"],
            ["读者写者", "第一个读者挡写者，最后一个放开", "推 3 读者 + 1 写者那道"],
        ],
        "tail": "一句话收口：<b>所有同步问题都是同一句算术——数一数谁在等、谁手里有东西</b>；数不清就会写出带着锁睡觉的代码。",
    },

    "quiz": {
        "no": "8", "zh": "自测", "en": "Self-check",
        "lec": "六题全是推演或小计算；答不出来就回对应小节，把那段代码或那张图再走一遍。",
        "items": [
            ("初值 count = 0，A、B 各执行一次 count++，写出能得到 1 的那种交错。",
             "答：A 读 0 → B 读 0 → A 写 1 → B 写 1，结果 1（丢一次更新）。回看 §2。"),
            ("严格轮换方案违反了哪两条要求？",
             "答：③ 区外进程会让别人阻塞（A 出区后 B 仍得等 turn）；④ 可能无限等待（A 挂掉后 B 永远等）。回看 §3。"),
            ("s 初值 1，A.down、B.down、A.up、B 重试 down，最后 s 等于多少？谁在临界区？",
             "答：s = 0，B 在临界区。up 会先唤醒 B 再让 s 加 1，B 重试时正好拿到 0。回看 §4。"),
            ("N = 100，生产 5 个、消费 2 个后，empty / full / mutex 各是多少？",
             "答：empty = 97、full = 3、mutex = 1（三者之和 101 可自查）。回看 §5。"),
            ("把生产者里两行 down 的顺序对调，会发生什么？为什么？",
             "答：死锁。生产者先拿到 mutex 再发现 empty = 0 而睡下，锁没释放；消费者等 mutex 永远进不去。回看 §5。"),
            ("五个哲学家都先拿左手叉时会怎样？给出两种破法。",
             "答：五人各持一把、互等另一把，形成循环等待而死锁。破法：① 只允许 4 人上桌（初值 4 的计数信号量）；② 奇偶顺序拿叉。回看 §6。"),
        ],
    },

    "glossary": {
        "no": "9", "zh": "术语表", "en": "Glossary",
        "lec": "本讲术语按首次出现排；英文是课件原词，写代码查文档都用它。",
        "rows": [
            ("进程间通信", "inter-process communication (IPC)", "课件 p.5", "进程之间传数据的机制"),
            ("管道", "pipe", "课件 p.5", "单向字节流，内核维护先进先出"),
            ("共享内存", "shared memory", "课件 p.10", "两块虚拟内存映射同一物理页，速度最快"),
            ("竞争条件", "race condition", "课件 p.44", "并发访问共享数据导致结果不确定"),
            ("丢失更新", "lost update", "本讲 §2", "两个写互相覆盖，只留最后一次"),
            ("临界区", "critical section", "课件 p.44", "访问共享对象的那段代码"),
            ("互斥", "mutual exclusion", "课件 p.44", "同一时刻只允许一个进程进临界区"),
            ("饥饿", "starvation", "课件 p.51", "某进程永远轮不到"),
            ("死锁", "deadlock", "本讲 §6", "互相等对方手里的资源，谁都不前进"),
            ("信号量", "semaphore", "课件 p.77", "用 down/up 控制进入与唤醒的计数变量"),
            ("二元信号量", "binary semaphore", "课件 p.85", "取值只有 0/1，当锁用"),
            ("计数信号量", "counting semaphore", "课件 p.85", "取值为 0..N，当资源计数用"),
            ("原子操作", "atomic operation", "课件 p.81", "要么全做完、要么没开始，中间不被切换"),
            ("生产者消费者", "producer-consumer", "课件 p.88", "有界缓冲上的一放一取"),
            ("有界缓冲", "bounded buffer", "课件 p.88", "容量 N 的环形队列"),
            ("哲学家问题", "dining philosophers", "课件 p.6", "五个进程争五把叉，经典死锁题"),
            ("读者写者", "readers-writers", "课件 p.6", "读可并发、写要独占"),
            ("读者优先", "reader preference", "本讲 §6", "新读者可直接进，写者可能饥饿"),
            ("唤醒", "wakeup", "课件 p.78", "up 把睡眠中的进程叫起来重试"),
            ("循环等待", "circular wait", "本讲 §6", "A 等 B、B 等 A，死锁的成因之一"),
        ],
    },

    "appendix": {
        "no": "10", "zh": "附录", "en": "Appendix",
        "lec": "一张算式速查加一组误解。速查那几条考试直接用。",
        "symbols": [
            ["empty + full", "恒等于 N（缓冲总数不变）", "本讲 §5"],
            ["mutex", "恒为 1（用完必须 up 回去）", "本讲 §5"],
            ["s > 0", "down 后 s 减 1，进程进入", "课件 p.78"],
            ["s = 0", "down 会让进程睡眠排队，等 up 唤醒", "课件 p.78"],
            ["p.N", "源 PDF 第 N 页（不是幻灯片编号）", "本讲义口径"],
        ],
        "myths_title": "常见误解",
        "myths": [
            "以为 count++ 是原子的：它是读、加、写三条指令，中间可以被切走。",
            "写反 down 的顺序：先拿 mutex 再等资源，就会带着锁睡觉 → 死锁。",
            "以为 up 是「先加一再唤醒」：顺序反了会在竞争激烈时多睡一轮甚至饿死。",
            "把临界区当成共享对象：临界区是代码段，共享对象才是被保护的东西。",
            "以为信号量能跨机器：它只在同一内核内有效，跨机器要分布式锁。",
        ],
    },

    "tail": [],
}
