# -*- coding: utf-8 -*-
"""L06 轻量级进程：线程 · 练习型讲义（代码 + 例题运算 + 结构图为主）。

来源：课件 L06_Light-WeightProcesses_Threads.pdf（48 页）。结构图按课件概念自绘（不再引用裁图），
引文 ('q', …, '课件 p.N') 均为课件原文短语；代码块按课件给出的 API 写成可编译的 POSIX 写法。

2026-11-16 返工：理论型改成练习型（每节至少一段代码或一道例题），一节一页。
"""

_A1 = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="16" fill="#A8A498" font-size="11">单线程进程</text>
  <rect x="14" y="24" width="150" height="18" fill="#161614" stroke="#2A2A24"/><text x="89" y="37" text-anchor="middle" fill="#F4F1E6" font-size="9">代码段（共享）</text>
  <rect x="14" y="46" width="150" height="18" fill="#161614" stroke="#2A2A24"/><text x="89" y="59" text-anchor="middle" fill="#F4F1E6" font-size="9">数据段 / 堆（共享）</text>
  <rect x="14" y="68" width="150" height="24" fill="#1C1B13" stroke="#E7C246"/><text x="89" y="84" text-anchor="middle" fill="#E7C246" font-size="9">栈（只有一份）</text>
  <text x="14" y="126" fill="#6E6B61" font-size="9">一条执行流：PC 只有一处</text>
  <text x="230" y="16" fill="#A8A498" font-size="11">多线程进程</text>
  <rect x="230" y="24" width="180" height="18" fill="#161614" stroke="#2A2A24"/><text x="320" y="37" text-anchor="middle" fill="#F4F1E6" font-size="9">代码段（共享，同一份）</text>
  <rect x="230" y="46" width="180" height="18" fill="#161614" stroke="#2A2A24"/><text x="320" y="59" text-anchor="middle" fill="#F4F1E6" font-size="9">数据段 / 堆（共享，可同时改）</text>
  <rect x="230" y="68" width="56" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="258" y="85" text-anchor="middle" fill="#E7C246" font-size="9">栈 1</text>
  <rect x="292" y="68" width="56" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="320" y="85" text-anchor="middle" fill="#E7C246" font-size="9">栈 2</text>
  <rect x="354" y="68" width="56" height="26" fill="#1C1B13" stroke="#E7C246"/><text x="382" y="85" text-anchor="middle" fill="#E7C246" font-size="9">栈 3</text>
  <text x="230" y="126" fill="#6E6B61" font-size="9">三条执行流：三个 PC、三个栈，共享同一地址空间</text>
  <path d="M206 82 L226 82" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#a1)"/>
  <defs><marker id="a1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker></defs>
</svg>"""

_A2 = """<svg viewBox="0 0 620 130" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="10" y="40" width="120" height="34" fill="#161614" stroke="#2A2A24"/><text x="70" y="62" text-anchor="middle" fill="#F4F1E6" font-size="10">① 主线程在跑</text>
  <rect x="166" y="40" width="120" height="34" fill="#1C1B13" stroke="#E7C246"/><text x="226" y="62" text-anchor="middle" fill="#E7C246" font-size="10">② create 建线程</text>
  <rect x="322" y="40" width="120" height="34" fill="#161614" stroke="#2A2A24"/><text x="382" y="62" text-anchor="middle" fill="#F4F1E6" font-size="10">③ 两条一起跑</text>
  <rect x="478" y="40" width="120" height="34" fill="#161614" stroke="#2A2A24"/><text x="538" y="62" text-anchor="middle" fill="#F4F1E6" font-size="10">④ join 等它结束</text>
  <path d="M132 57 L162 57" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#a2)"/>
  <path d="M288 57 L318 57" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#a2)"/>
  <path d="M444 57 L474 57" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#a2)"/>
  <text x="166" y="26" fill="#6E6B61" font-size="9">pthread_create(&amp;tid, NULL, 函数, 参数)</text>
  <text x="478" y="26" fill="#6E6B61" font-size="9">pthread_join 期间主线程 BLOCKED</text>
  <text x="166" y="96" fill="#6E6B61" font-size="9">③ 与 ② 之间谁先谁后不确定 —— 这正是后面竞争条件的来源</text>
  <defs><marker id="a2" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker></defs>
</svg>"""

_A3 = """<svg viewBox="0 0 620 130" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <text x="14" y="18" fill="#A8A498" font-size="11">加锁前（结果 1 或 2，看调度）</text>
  <rect x="14" y="26" width="86" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="57" y="41" text-anchor="middle" fill="#E7C246" font-size="9">T1 读 0</text>
  <rect x="106" y="26" width="86" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="149" y="41" text-anchor="middle" fill="#E7C246" font-size="9">T2 读 0</text>
  <rect x="198" y="26" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="241" y="41" text-anchor="middle" fill="#F4F1E6" font-size="9">T1 写 1</text>
  <rect x="290" y="26" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="333" y="41" text-anchor="middle" fill="#F4F1E6" font-size="9">T2 写 1</text>
  <text x="386" y="42" fill="#E6392F" font-size="10">丢一次更新</text>
  <text x="14" y="82" fill="#A8A498" font-size="11">加锁后（串行，结果一定 2）</text>
  <rect x="14" y="90" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="57" y="105" text-anchor="middle" fill="#F4F1E6" font-size="9">T1 拿锁</text>
  <rect x="106" y="90" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="149" y="105" text-anchor="middle" fill="#F4F1E6" font-size="9">T1 读 1 改 2 放锁</text>
  <rect x="198" y="90" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="241" y="105" text-anchor="middle" fill="#F4F1E6" font-size="9">T2 拿锁</text>
  <rect x="290" y="90" width="86" height="22" fill="#161614" stroke="#2A2A24"/><text x="333" y="105" text-anchor="middle" fill="#F4F1E6" font-size="9">T2 读 2 改 3 放锁</text>
  <text x="386" y="106" fill="#E7C246" font-size="10">结果 3 ✓</text>
</svg>"""

_A4 = """<svg viewBox="0 0 620 130" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="14" y="34" width="150" height="40" rx="4" fill="#161614" stroke="#2A2A24"/><text x="89" y="59" text-anchor="middle" fill="#F4F1E6" font-size="10">消费者：缓冲空</text>
  <rect x="200" y="30" width="200" height="22" fill="#1C1B13" stroke="#E7C246"/><text x="300" y="45" text-anchor="middle" fill="#E7C246" font-size="10">cond_wait(&amp;empty, &amp;mutex)</text>
  <rect x="200" y="58" width="200" height="22" fill="#161614" stroke="#2A2A24"/><text x="300" y="73" text-anchor="middle" fill="#F4F1E6" font-size="10">睡着，同时把 mutex 放开</text>
  <rect x="440" y="34" width="166" height="40" rx="4" fill="#161614" stroke="#2A2A24"/><text x="523" y="59" text-anchor="middle" fill="#F4F1E6" font-size="10">生产者：放了一个</text>
  <path d="M168 54 L196 42" stroke="#8FA7B8" stroke-width="1.1" marker-end="url(#a4)"/>
  <path d="M404 69 C420 92 470 92 500 76" stroke="#E7C246" stroke-width="1.1" fill="none" marker-end="url(#a4b)"/>
  <text x="14" y="100" fill="#6E6B61" font-size="9">① wait 前必须持锁；② 被唤醒时 cond_wait 会重新加锁，所以醒来第一件事是复查条件</text>
  <text x="14" y="118" fill="#6E6B61" font-size="9">③ signal 只叫醒一个；要叫醒全部用 broadcast</text>
  <defs>
    <marker id="a4" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker>
    <marker id="a4b" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker>
  </defs>
</svg>"""

LESSON = {
    "code": "CS340",
    "no": "L06",
    "zh": "轻量级进程：线程",
    "en": "Light-Weight Processes: Threads",
    "out": "L06_线程_讲义.pdf",
    "sub": "讲义 · 练习型 ｜ 代码 + 例题运算 + 结构图 ｜ 从「一个进程一条执行流」走到 pthread 的互斥与同步",
    "meta": [
        ("源课件", "L06_Light-WeightProcesses_Threads.pdf，48 页"),
        ("本讲口径", "以代码与推演为主：每节至少一段可跑代码或一道带数的例题，理论只解释为什么这么写"),
        ("图", "结构图按课件概念自绘（不再按页裁原图），所以没有外部图片依赖"),
        ("页码口径", "「课件 p.N」指源 PDF 的页序（共 48 页），不是幻灯片编号"),
        ("怎么读", "§1–§2 线程是什么 → §3 创建与 join → §4 函数指针 → §5–§6 互斥与坑 → §7 条件变量 → §8 模型与调度 → §9 线程安全"),
        ("动手指令", "Linux / WSL 下 `gcc -pthread xxx.c -o xxx`；忘了 `-pthread` 会报一堆 undefined reference"),
        ("原文在哪", "CS340\\01_讲义\\L06_Light-WeightProcesses_Threads.pdf；本讲义只讲，不复制全文"),
    ],

    "sections": [
        {
            "no": "0", "zh": "本讲导读", "en": "How to Use This Handout",
            "lec": "这讲以前几讲的「一个进程一条执行流」为起点，把一条变成多条。理论只有两句：线程共享地址空间、栈各一份；代价是共享带来的互斥与同步。",
            "body": [
                ("p", "<b>这一节能解决什么。</b>三个具体问题：① 一个进程里怎么同时跑几段代码；② 它们共享什么、私有什么，哪块内存会被两条线程同时改；③ 用 pthread 怎么创建、等待、加锁、等条件。"),
                ("p", "<b>这一节不能解决什么。</b>不讲内核的调度算法（L04）、进程间通信（L05）、内存分配（L08–L09）；也不讲无锁编程与内存模型，本讲的锁只有互斥量与条件变量两种。"),
                ("p", "<b>每节都有一道能算的题</b>：三条线程各加 10 万次该得多少、wait 时锁在谁手里、两个模型下一个阻塞会拖累谁——算不出来就是没懂。"),
                ("note", "本讲地图", "线程是什么（§1）→ 共享与私有（§2）→ create/join（§3）→ 函数指针（§4）→ 互斥（§5）→ 忘记解锁的坑（§6）→ 条件变量（§7）→ 模型与调度（§8）→ 线程安全（§9）。"),
            ],
        },
        {
            "no": "1", "zh": "什么是线程：一个进程几条执行流", "en": "What Is a Thread",
            "lec": "定义只有一句：线程是进程内部的执行实体。短定义容易让人以为「没啥新东西」，所以课件马上给了对照——你之前学的进程只有一条执行流，加上第二条就叫多线程进程。",
            "body": [
                ("q", "A thread is an execution entity within a process. The process that we've learnt is a single-threaded process. … We called this kind of process the multi-threaded process.", "课件 p.3"),
                ("svg", _A1, "图 1　单线程与多线程进程：代码段、数据段、堆是同一份；栈是每个线程一份"),
                ("p", "课件 p.4 的例子最好记：一个播放器进程里同时有三条执行流——从网络读数据、等用户输入、执行 Flash 播放。课件说这三条是「并行」跑的，但它们共用同一个 PID。"),
                ("eg", "播放器进程里三条线程：读网络、等键盘、解码播放。问：这个进程有几个 PID？哪条线程阻塞了会拖住另外两条？",
                 ["PID 只有一个——三条线程都在同一进程里，共用地址空间",
                  "等键盘的那条会进入 BLOCKED，另外两条照跑（这正是课件 p.9 说的「多任务」）",
                  "如果三条是三个进程，传数据就得走内核（L05 的 IPC），成本更高"],
                 "答案：一个 PID；阻塞互不拖累。课件 p.10 的例子就是把键盘输入直接写进数据段，另一条线程直接读。"),
            ],
        },
        {
            "no": "2", "zh": "共享什么、私有什么", "en": "Shared vs Private",
            "lec": "这节是全讲最重要的一张对照：代码段、数据段、堆是大家共用的，栈是每人一份的。想通这一点，后面所有麻烦（竞争、互斥、同步）都能自己推出来——因为麻烦全部来自「共享」。",
            "body": [
                ("code", "c", "/* where.c —— 四类变量各在哪块内存 */\n#include <stdio.h>\n#include <stdlib.h>\nint    g_init = 1;          /* data 段：已初始化的全局变量 */\nint    g_bss;               /* BSS 段：未初始化的全局变量 */\nint main(void) {\n    int  local = 2;         /* 栈：每个线程私有 */\n    int *heap  = malloc(sizeof(int));   /* 堆：所有线程共享 */\n    printf(\"global=%p bss=%p local=%p heap=%p\\n\",\n           (void*)&g_init, (void*)&g_bss, (void*)&local, (void*)heap);\n    free(heap);\n    return 0;\n}", "跑两次，你会看到 local 的地址会变、global 不会变"),
                ("p", "课件 p.6 讲代码段：所有线程共享同一段代码，每个线程从「线程函数」开始执行；它<b>永远不能返回给线程函数的调用者</b>——因为调用它的不是某段代码，是创建它的系统调用。"),
                ("p", "课件 p.7 讲数据段与堆：两块都共享，都能读写；课件随即追问「多线程进程是不是天生带着竞争条件问题」——这就是 §5 的入口。课件 p.8 讲栈：每个线程有自己的栈，所以局部变量天然互不干扰。"),
                ("eg", "四个变量：全局 int g、静态局部 int s、函数内 int local、malloc 出来的 p。哪些能被别的线程读到并改掉？",
                 ["g 在 data 段 → 共享，能改",
                  "s 在数据段（静态局部变量也是全局类存储）→ 共享，能改",
                  "local 在栈上 → 各线程一份，别的线程拿不到",
                  "p 指向堆 → 共享，能改（指针本身在栈上，但它指向的空间共享）"],
                 "答案：g、s、*p 都能被同时改；local 不能。所以「加锁保护谁」的答案，永远是共享的那几块（课件 p.7–p.8）。"),
            ],
        },
        {
            "no": "3", "zh": "pthread 创建与 join", "en": "Creating and Joining Threads",
            "lec": "这节把最小可用例子拆成四步：主线程存在 → 创建 → 两条一起跑 → 主线程 join 等它结束。join 和 wait 是同一个语义，这是让主线程「不抢先退出」的关键。",
            "body": [
                ("code", "c", "/* hello.c —— 最小可用：创建一条线程并等它结束 */\n#include <pthread.h>\n#include <stdio.h>\nvoid *hello(void *input) {        /* 线程函数：签名必须是 void *f(void *) */\n    printf(\"%s\\n\", (char *)input);\n    pthread_exit(NULL);           /* 只能退出，没有「调用者」可返回 */\n}\nint main(void) {\n    pthread_t tid;\n    pthread_create(&tid, NULL, hello, \"hello world\");\n    pthread_join(tid, NULL);      /* 相当于 wait：主线程在此 BLOCKED */\n    return 0;\n}\n/* gcc -pthread hello.c -o hello */", "课件 p.16–p.17 的十行程序，加了编译命令"),
                ("svg", _A2, "图 2　create → 一起跑 → join 的四个阶段；join 期间主线程处于 BLOCKED"),
                ("eg", "上面程序把 `pthread_join(tid, NULL)` 这一行删掉，可能看到什么？为什么？",
                 ["主线程 main 立刻 return → 整个进程结束，hello 线程被强行带走",
                  "于是有时打印得出 hello world、有时一行都不打印——取决于调度给谁先跑",
                  "这就是「主线程不等就退出」的典型症状：不是线程没建，是进程没了"],
                 "答案：可能一行都不打印。课件 p.20 特意问「还记得 wait() 与 waitpid() 吗」——join 就是同一个语义：等子实体结束再继续。"),
            ],
        },
        {
            "no": "4", "zh": "函数指针：第三个参数怎么读", "en": "Function Pointers",
            "lec": "为什么突然讲 C 语言？因为 pthread_create 的第三个参数就是函数指针。看不懂那行声明，后面所有线程例子都读不下去。这节只讲三件事：怎么定义、怎么赋值、怎么调用。",
            "body": [
                ("code", "c", "/* 定义 */\nint (*fp) (int, char, int);      /* fp 指向「收三个参数、返回 int」的函数 */\nint  add(int a, char b, int c) { return a + b + c; }\n\n/* 赋值：两种写法等价 */\nfp = add;          /* 或 */ fp = &add;\n\n/* 调用：两种写法等价 */\nint r1 = fp(7, 'A', 2);          /* 或 */ int r2 = (*fp)(7, 'A', 2);\n\n/* 线程要的是「收一个 void*、返回 void*」那种 */\nvoid *(*fn)(void *) = hello;     /* 这就是 pthread_create 的第三个参数类型 */", "课件 p.13–p.15；(*fp) 这对括号不能省"),
                ("p", "课件 p.12 讲动机：函数占内存，所以每个函数都有地址；把函数当参数传给「控制函数」能提高灵活性——排序时换比较函数、线程库换线程体，都是这条。"),
                ("eg", "判断这四行分别声明了什么：① `int *f(int)`；② `int (*f)(int)`；③ `void *f(void *)`；④ `void (*f)(void *)`。",
                 ["① 是函数：收 int、返回 int 指针 —— 不是函数指针",
                  "② 是函数指针：指向「收 int、返回 int」的函数",
                  "③ 是函数：收 void*、返回 void* —— 标准线程函数就是这个签名",
                  "④ 是函数指针：指向「收 void*、返回 void」的函数"],
                 "答案：①③ 是函数，②④ 是函数指针。判据只有一条：<b>`(*f)` 外面有没有那对括号</b>；有括号才是指针（课件 p.13）。"),
            ],
        },
        {
            "no": "5", "zh": "互斥：共享计数为什么少", "en": "Mutual Exclusion",
            "lec": "回到 §2 埋下的隐患：共享变量可能被两条线程同时改。先跑出证据（结果小于期望值），再用互斥量把它修好——这两步都要自己动手，光看结论记不住。",
            "body": [
                ("code", "c", "/* badcounter.c —— 4 条线程各加 10 万次，期望 400000 */\n#include <pthread.h>\n#include <stdio.h>\n#define N 100000\nint counter = 0;                        /* 全局变量：所有线程共享 */\nvoid *work(void *arg) {\n    for (int i = 0; i < N; i++) counter++;   /* 读-加-写三步，不是原子 */\n    return NULL;\n}\nint main(void) {\n    pthread_t t[4];\n    for (int i = 0; i < 4; i++) pthread_create(&t[i], NULL, work, NULL);\n    for (int i = 0; i < 4; i++) pthread_join(t[i], NULL);\n    printf(\"counter = %d（期望 %d）\\n\", counter, 4 * N);\n    return 0;\n}", "多跑几次，每次的结果都不一样，而且都小于 400000"),
                ("svg", _A3, "图 3　同一个 ++ 的两种执行：不加锁会丢更新，加锁后排成一条队"),
                ("eg", "4 条线程各加 10 万次、实测 21 万–29 万之间浮动。用「读-加-写」模型解释小了多少。",
                 ["每次交错丢一次更新，丢失次数取决于调度时机（不可预测）",
                  "4 条线程的循环越长，可交错的点越多，丢得越多",
                  "所以结果是一个分布，不是固定值；加锁之后必然等于 400000"],
                 "答案：因为「读」与「写」之间被打断就丢一次。课件 p.10 说共享数据会带来互斥问题，p.27 给的工具就是互斥量（mutex，本质是二值信号量）。"),
            ],
        },
        {
            "no": "6", "zh": "互斥的坑：忘记解锁", "en": "Lock Discipline",
            "lec": "加锁保护起来以后，最常见的两个错误是「某条路径忘了解锁」和「把互斥量当计数器」。这节把正确的写法写全——尤其 break、return 之前必须解锁，否则其余线程全卡住。",
            "body": [
                ("code", "c", "/* goodcounter.c —— 正确写法：出口只有一处能拿走锁 */\npthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;   /* 初始状态：未锁 */\n#define MAX 400000\nvoid *work(void *arg) {\n    for (;;) {\n        pthread_mutex_lock(&m);                  /* 已锁 → 本线程阻塞 */\n        if (counter >= MAX) {\n            pthread_mutex_unlock(&m);            /* 提前退出也必须解锁！ */\n            break;\n        }\n        counter++;\n        pthread_mutex_unlock(&m);                /* 本来就未锁时啥也不做 */\n    }\n    return NULL;\n}", "课件 p.28–p.31；p.31 在最后那个 unlock 上写了「Can this be removed?」"),
                ("p", "课件 p.27 讲初始化与类型，p.28 讲 lock：把状态从未锁改为已锁，已锁时调用会阻塞；p.29 讲 unlock：把已锁改回未锁，本来就未锁时什么也不做。注意它是<b>二值</b>信号量，只有两个状态。"),
                ("eg", "把上面那段里的 `pthread_mutex_unlock(&m);`（break 之前那一行）删掉，程序会怎样？",
                 ["counter 到 MAX 的那条线程 break 出去，锁仍握在它手里",
                  "其余线程下一次 pthread_mutex_lock 全部永久阻塞",
                  "主线程 join 等到的是「永远等不完」——程序卡住不动"],
                 "答案：死锁。这正是课件 p.31 那个「Can this be removed?」的答案：不能。规则一句话——<b>哪条路径拿走锁，哪条路径就负责还</b>。"),
            ],
        },
        {
            "no": "7", "zh": "条件变量：等一个条件", "en": "Condition Variables",
            "lec": "互斥解决「不能同时改」，条件变量解决「顺序要对」。课件用打电话叫醒的比喻：消费者睡前留个电话，生产者有货就打那个电话。关键一句是 wait 会原子地放锁，否则就会「拿着锁睡觉」。",
            "body": [
                ("code", "c", "/* 生产者：满了就睡在 not_full 上，放完叫醒消费者 */\npthread_mutex_t m = PTHREAD_MUTEX_INITIALIZER;\npthread_cond_t  not_full  = PTHREAD_COND_INITIALIZER;\npthread_cond_t  not_empty = PTHREAD_COND_INITIALIZER;\nint buf[N], count = 0;\nvoid *producer(void *p) {\n    pthread_mutex_lock(&m);\n    while (count == N) pthread_cond_wait(&not_full, &m);  /* 先放锁再睡 */\n    buf[count++] = 1;\n    pthread_cond_signal(&not_empty);                      /* 叫醒一个消费者 */\n    pthread_mutex_unlock(&m);\n    return NULL;\n}", "课件 p.38–p.42；wait 必须放在 while 里，被唤醒不等于条件成立"),
                ("svg", _A4, "图 4　条件变量的一次往返：消费者 wait 时放锁并睡，生产者 signal 后它重新加锁"),
                ("eg", "count = N（缓冲满）时生产者执行到 cond_wait。问：此刻 mutex 在谁手里？消费者能不能进去取数据？",
                 ["wait 前生产者持锁；进入 wait 时它原子地释放 mutex 并阻塞",
                  "于是 mutex = 1，消费者可以 lock 进去取数据",
                  "取完 up 一个空位后 signal(&not_full)：生产者被唤醒，并在 wait 返回前重新拿到 mutex"],
                 "答案：wait 期间锁是自由的，消费者能进。若 wait 不放锁，消费者永远进不去——这就是「拿着锁睡觉」的死锁（课件 p.38）。"),
            ],
        },
        {
            "no": "8", "zh": "线程模型与谁在调度", "en": "Models and Scheduling",
            "lec": "用户态线程要落地，必须和内核线程对上号：全塞进一个内核线程（多对一），或者一个对一个（一对一）。这节的判据很实用——问「一个阻塞调用会不会拖住全部」，答案就把模型暴露出来了。",
            "body": [
                ("table", ["模型", "映射方式", "好处", "坏处", "用过的系统"],
                 [["多对一many-to-one", "所有用户线程 → 一个内核线程", "内核实现简单", "一个阻塞调用阻塞全部", "老版本 UNIX"],
                  ["一对一one-to-one", "一条用户线程 → 一个内核线程", "只管阻塞调用者，并发度高", "线程数受内核内存限制", "Linux、Windows"]],
                 ["18%", "26%", "20%", "22%", "14%"]),
                ("p", "课件 p.22–p.23 就是这两段话。一对一那个「坏处」很现实：每条线程都要内核结构与栈，开太多会撑爆内核内存——所以「线程数」要当资源来规划。"),
                ("p", "课件 p.24 讲进程级调度器：它只认进程，不知道线程，于是线程库得自己在用户态再排一次队（两层调度）。课件 p.25 讲线程级调度器：只认线程，普通进程在它眼里就是一条线程——Linux 2.6 起就是这样。"),
                ("eg", "某系统上，一条线程调用 read() 阻塞后整个进程的其余线程全部停住。它更像哪种模型？换到 Linux 上同一段程序会怎样？",
                 ["一条阻塞拖住全部 → 多对一模型：用户线程共用内核里的那一条",
                  "Linux 是一对一：read 只阻塞调用者，其余线程继续跑",
                  "代价是一对一更吃内核内存，线程数不能无限开"],
                 "答案：多对一。判据就是「阻塞是否传染」（课件 p.22–p.23）；而 Linux 的调度器直接认线程（课件 p.25），所以不会传染。"),
            ],
        },
        {
            "no": "9", "zh": "线程安全：strtok 与 strtok_r", "en": "Thread Safety",
            "lec": "最后一节讲一类「不是你的 bug，但会咬你」的问题：有些库函数按单线程设计，把状态藏在全局变量里。strtok 是最典型的例子，解法很朴素——换成把状态交给你保管的那一版。",
            "body": [
                ("code", "c", "/* 同一条字符串，两条线程同时解析：前者互相踩状态 */\nchar *tok = strtok(line, \" \");             /* 状态藏在库的全局变量里 */\nwhile (tok) { handle(tok); tok = strtok(NULL, \" \"); }\n\n/* 线程安全版：save 是「每线程自己的一份状态」 */\nchar *save = NULL;\nchar *tok = strtok_r(line, \" \", &save);\nwhile (tok) { handle(tok); tok = strtok_r(NULL, \" \", &save); }", "课件 p.44–p.45；_r 后缀就是 reentrant（可重入）"),
                ("p", "课件 p.44 讲现象：strtok 假定只有一条执行流，内部用全局结构记录「解析到哪」；两条线程同时用就会互相踩，这种问题叫线程安全（thread safety）。p.45 给解法：把它换成实现了<b>可重入</b>（reentrant）性质的版本，多出来的 <code>_r</code> 表示状态由调用者提供。"),
                ("eg", "两条线程各自解析 \"a b c\" 与 \"x y z\"，都用 strtok。可能出现什么结果？换了 strtok_r 呢？",
                 ["两次调用共用一个静态状态 → 可能 A 拿到 x、B 拿到 b，两串混着出来",
                  "严重时死循环或读到 NULL 提前结束（取决于交错）",
                  "strtok_r 每个线程传自己的 save 指针 → 两串各走各的，结果确定"],
                 "答案：strtok 的结果不确定；strtok_r 确定。判据不是「有没有加锁」，而是<b>状态存在谁那里</b>（课件 p.45）。"),
            ],
        },
    ],

    "summary": {
        "no": "10", "zh": "本讲小结", "en": "Takeaways",
        "lec": "收口用一张表：每行都配一个能动手验的动作。",
        "head": ["记住什么", "一句话", "怎么自查"],
        "head_widths": ["20%", "52%", "28%"],
        "rows": [
            ["线程是什么", "进程内部的执行实体，共用同一个 PID", "说清播放器三条执行流"],
            ["共享 / 私有", "代码段、数据段、堆共享；栈私有", "跑 where.c 看四类地址"],
            ["create / join", "四个参数；join 相当于 wait", "删掉 join 看结果变随机"],
            ["函数指针", "(*f) 有括号才是指针", "读 §4 那四行声明"],
            ["mutex", "lock 会阻塞、unlock 不阻塞", "跑 badcounter.c 看少多少"],
            ["忘记解锁", "哪条路径拿走锁就负责还", "删掉 break 前的 unlock 会卡死"],
            ["条件变量", "wait 原子放锁；signal 叫醒一个", "推 §7 那道「锁在谁手里」"],
            ["模型", "多对一阻塞会传染，一对一不会", "判一个阻塞是否拖住全部"],
            ["线程安全", "看状态存在谁那里，不看有没有加锁", "说明 strtok 与 strtok_r 差别"],
        ],
        "tail": "一句话收口：<b>线程把「进程内部的并发」变成可能，代价是共享</b>——所以每次共享都要问一句：谁在改、谁在等、锁在谁手里。",
    },

    "quiz": {
        "no": "11", "zh": "自测", "en": "Self-check",
        "lec": "六题只用本讲内容：前三题判共享与创建，后三题判锁与条件变量。",
        "items": [
            ("线程与进程的根本区别是什么？同一个进程里的两条线程 PID 一样吗？",
             "答：线程是进程内部的执行实体，共享地址空间（代码段、数据段、堆），只有栈私有；同一进程内的线程 PID 相同（课件 p.3、p.6–p.8）。回看 §1–§2。"),
            ("多线程进程里哪些区域可能被同时读写？哪些一定不会？",
             "答：数据段（全局/静态）与堆可能被同时读写；栈是每个线程一份，局部变量不受影响（课件 p.7–p.8）。回看 §2。"),
            ("pthread_create 的四个参数分别是什么？删掉 pthread_join 会怎样？",
             "答：接收 tid 的指针、属性（NULL 表示默认）、线程函数（函数指针）、传给线程函数的参数（课件 p.16）；删掉 join 主线程可能先退出，整个进程结束（课件 p.20）。回看 §3。"),
            ("4 条线程各把共享 counter 加 10 万次，不加锁时为什么不到 400000？",
             "答：counter++ 是读-加-写三步，两条线程在读写之间交错就丢一次更新；丢几次取决于调度（课件 p.10、p.27）。回看 §5。"),
            ("加锁后如果某条路径忘了 unlock 会怎样？标准写法把 unlock 放在哪？",
             "答：其余线程全部卡在 lock 上（死锁）；每个退出路径（含 break）之前都必须 unlock（课件 p.31）。回看 §6。"),
            ("pthread_cond_wait 为什么必须同时传 mutex？被唤醒后还要复查条件吗？",
             "答：它在阻塞前原子释放 mutex、被唤醒时原子重新加锁，避免拿着锁睡觉；被唤醒不等于条件成立，所以 wait 要放在 while 里（课件 p.38）。回看 §7。"),
        ],
    },

    "glossary": {
        "no": "12", "zh": "术语表", "en": "Glossary",
        "lec": "本讲术语按首次出现排；英文是课件原词，写代码查文档都用它。",
        "rows": [
            ("线程", "thread", "课件 p.3", "进程内部的执行实体"),
            ("单线程进程", "single-threaded process", "课件 p.3", "只有一条执行流"),
            ("多线程进程", "multi-threaded process", "课件 p.3", "一个进程里有多条执行流"),
            ("线程函数", "thread function", "课件 p.6", "线程的入口函数，签名 void *f(void *)"),
            ("代码段", "code segment", "课件 p.6", "所有线程共享"),
            ("数据段", "data segment", "课件 p.7", "所有线程共享，可同时读写"),
            ("堆", "heap", "课件 p.7", "所有线程共享的动态内存"),
            ("栈", "stack", "课件 p.8", "每个线程私有"),
            ("竞争条件", "race condition", "课件 p.7", "共享数据被同时改，结果不确定"),
            ("互斥", "mutual exclusion", "课件 p.10", "同一时刻只让一个线程进临界区"),
            ("同步", "synchronization", "课件 p.10", "协调线程之间的执行顺序"),
            ("轻量级进程", "light-weight process", "课件 p.1", "线程的别名（进程内切换不用换地址空间）"),
            ("pthread 库", "POSIX thread library", "课件 p.11", "Linux 的线程库，链接要 -pthread"),
            ("线程标识", "pthread_t", "课件 p.16", "线程的 ID 类型"),
            ("多对一模型", "many-to-one model", "课件 p.22", "多条用户线程映射到一个内核线程"),
            ("一对一模型", "one-to-one model", "课件 p.23", "一条用户线程对应一个内核线程"),
            ("进程级调度器", "process-based scheduler", "课件 p.24", "只认进程，不知道线程"),
            ("线程级调度器", "thread-based scheduler", "课件 p.25", "只认线程，普通进程也算一条"),
            ("互斥量", "mutex", "课件 p.27", "二值信号量：只有锁/未锁两态"),
            ("条件变量", "condition variable", "课件 p.38", "等一个条件成立，wait 时自动放锁"),
            ("可重入", "reentrant", "课件 p.45", "状态由调用者保管，可被多条线程同时用"),
            ("线程安全", "thread safety", "课件 p.44", "多线程调用不出错"),
        ],
    },

    "appendix": {
        "no": "13", "zh": "附录", "en": "Appendix",
        "lec": "一张函数速查加一组误解。速查那几条写代码时直接用。",
        "symbols": [
            ("pthread_create", "创建线程，四个参数", "课件 p.16"),
            ("pthread_join", "等线程结束，相当于 wait", "课件 p.16、p.20"),
            ("pthread_exit", "线程退出（不能 return 给调用者）", "课件 p.6、p.16"),
            ("pthread_mutex_t", "互斥量类型，PTHREAD_MUTEX_INITIALIZER 初始化", "课件 p.27"),
            ("pthread_mutex_lock", "加锁，已锁时阻塞", "课件 p.28"),
            ("pthread_cond_t", "条件变量类型，PTHREAD_COND_INITIALIZER 初始化", "课件 p.38"),
            ("pthread_cond_wait", "等待条件：原子放锁 + 阻塞，醒来重新加锁", "课件 p.38"),
            ("-pthread", "编译时必须链上线程库", "课件 p.11"),
        ],
        "myths_title": "常见误解",
        "myths": [
            "以为线程有自己的地址空间：代码段、数据段、堆都共享，只有栈私有。",
            "以为局部变量也可能被别的线程改：它在自己的栈上，别的线程拿不到地址。",
            "把函数名当函数指针用：签名必须是 void *f(void *)，参数类型不对编译就过不去。",
            "以为 wait 之后条件一定成立：被唤醒可能被别人抢先，必须 while 复查。",
            "以为标准库都线程安全：strtok 需要换 strtok_r，状态交给调用者保管。",
        ],
    },

    "tail": [],
}
