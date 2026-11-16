# -*- coding: utf-8 -*-
"""L01 操作系统是什么 · 讲义数据（练习型：代码 + 例题运算 + 结构图为主，理论只作铺垫）。

口径（用户 2026-11-16 定）：不要以课程理论为主；代码、题目运算才是重点；需要时配结构示意图。
引文：('q', 原文, '课件 p.N') 的英文原句取自 L01_IntroductionToOS.pdf（72 页）文本层，逐页核对。
"""

_LAYERS = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="120" y="8" width="380" height="34" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="310" y="30" text-anchor="middle" fill="#F4F1E6" font-size="13">用户：shell / 浏览器 / 你的程序</text>
  <rect x="120" y="58" width="380" height="34" rx="4" fill="#1C1B13" stroke="#E7C246"/>
  <text x="310" y="80" text-anchor="middle" fill="#E7C246" font-size="13">操作系统（内核态跑的这层软件）</text>
  <rect x="120" y="108" width="380" height="34" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="310" y="130" text-anchor="middle" fill="#F4F1E6" font-size="13">硬件：CPU / 内存 / 磁盘 / I/O</text>
  <path d="M310 42 L310 56" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#a1)"/>
  <path d="M310 92 L310 106" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#a1)"/>
  <defs><marker id="a1" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
    <path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker></defs>
  <text x="322" y="55" fill="#6E6B61" font-size="9">系统调用</text>
  <text x="322" y="105" fill="#6E6B61" font-size="9">设备驱动 / 中断</text>
</svg>"""

_SYSCALL = """<svg viewBox="0 0 620 160" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="16" y="10" width="250" height="140" rx="4" fill="none" stroke="#2A2A24"/>
  <text x="141" y="30" text-anchor="middle" fill="#A8A498" font-size="11">用户态</text>
  <rect x="352" y="10" width="250" height="140" rx="4" fill="none" stroke="#E7C246"/>
  <text x="477" y="30" text-anchor="middle" fill="#E7C246" font-size="11">内核态</text>
  <rect x="46" y="52" width="190" height="30" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="141" y="72" text-anchor="middle" fill="#F4F1E6" font-size="11">进程调用 time()</text>
  <rect x="382" y="52" width="190" height="30" rx="4" fill="#1C1B13" stroke="#E7C246"/>
  <text x="477" y="72" text-anchor="middle" fill="#E7C246" font-size="11">陷阱进入内核</text>
  <rect x="382" y="104" width="190" height="30" rx="4" fill="#161614" stroke="#2A2A24"/>
  <text x="477" y="124" text-anchor="middle" fill="#F4F1E6" font-size="11">读时钟 → 回填返回值</text>
  <path d="M240 67 L376 67" stroke="#8FA7B8" stroke-width="1.2" stroke-dasharray="4 3"/>
  <path d="M240 119 L376 119" stroke="#E7C246" stroke-width="1.2" stroke-dasharray="4 3"/>
  <path d="M477 86 L477 100" stroke="#8FA7B8" stroke-width="1.2"/>
  <text x="250" y="60" fill="#6E6B61" font-size="9">① 请求</text>
  <text x="250" y="112" fill="#6E6B61" font-size="9">④ 返回结果</text>
</svg>"""

_STATE = """<svg viewBox="0 0 620 150" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <circle cx="60" cy="70" r="26" fill="#161614" stroke="#2A2A24"/>
  <text x="60" y="74" text-anchor="middle" fill="#F4F1E6" font-size="11">新建</text>
  <circle cx="200" cy="70" r="26" fill="#161614" stroke="#2A2A24"/>
  <text x="200" y="74" text-anchor="middle" fill="#F4F1E6" font-size="11">就绪</text>
  <circle cx="350" cy="70" r="26" fill="#1C1B13" stroke="#E7C246"/>
  <text x="350" y="74" text-anchor="middle" fill="#E7C246" font-size="11">运行</text>
  <circle cx="500" cy="70" r="26" fill="#161614" stroke="#2A2A24"/>
  <text x="500" y="74" text-anchor="middle" fill="#F4F1E6" font-size="11">阻塞</text>
  <text x="560" y="74" fill="#6E6B61" font-size="11">结束</text>
  <path d="M86 70 L170 70" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#a2)"/>
  <path d="M226 70 L320 70" stroke="#8FA7B8" stroke-width="1.2" marker-end="url(#a2)"/>
  <path d="M350 44 C350 16 200 16 200 42" stroke="#8FA7B8" stroke-width="1.2" fill="none" marker-end="url(#a2)"/>
  <path d="M376 70 L470 70" stroke="#E7C246" stroke-width="1.2" marker-end="url(#a3)"/>
  <path d="M474 92 C420 122 240 122 206 94" stroke="#E7C246" stroke-width="1.2" fill="none" marker-end="url(#a3)"/>
  <path d="M376 70 L532 70" stroke="#6E6B61" stroke-width="1.2" stroke-dasharray="4 3"/>
  <defs>
    <marker id="a2" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#8FA7B8"/></marker>
    <marker id="a3" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="#E7C246"/></marker>
  </defs>
  <text x="112" y="60" fill="#6E6B61" font-size="9">就绪</text>
  <text x="262" y="60" fill="#6E6B61" font-size="9">被调度</text>
  <text x="410" y="60" fill="#6E6B61" font-size="9">等 I/O</text>
  <text x="300" y="138" fill="#6E6B61" font-size="9">I/O 完成 → 回就绪</text>
</svg>"""

_MEMHIER = """<svg viewBox="0 0 620 170" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei, sans-serif">
  <rect x="40" y="12" width="150" height="28" fill="#1C1B13" stroke="#E7C246"/>
  <text x="115" y="31" text-anchor="middle" fill="#E7C246" font-size="11">寄存器 1 ns</text>
  <rect x="40" y="48" width="220" height="28" fill="#161614" stroke="#2A2A24"/>
  <text x="150" y="67" text-anchor="middle" fill="#F4F1E6" font-size="11">L1 缓存 1 ns / L2 10 ns</text>
  <rect x="40" y="84" width="300" height="28" fill="#161614" stroke="#2A2A24"/>
  <text x="190" y="103" text-anchor="middle" fill="#F4F1E6" font-size="11">主存 100 ns</text>
  <rect x="40" y="120" width="380" height="28" fill="#161614" stroke="#2A2A24"/>
  <text x="230" y="139" text-anchor="middle" fill="#F4F1E6" font-size="11">磁盘 10 ms（比主存慢 10 万倍）</text>
  <path d="M400 26 L400 134" stroke="#6E6B61" stroke-width="1" stroke-dasharray="3 3"/>
  <text x="410" y="60" fill="#6E6B61" font-size="9">越快越贵越少</text>
  <text x="410" y="110" fill="#6E6B61" font-size="9">越慢越便宜越多</text>
</svg>"""

LESSON = {
    "code": "CS340",
    "no": "L01",
    "zh": "操作系统是什么",
    "en": "Introduction to Operating Systems",
    "out": "L01_操作系统是什么_讲义.pdf",
    "sub": "讲义 · 练习型 ｜ 代码 + 例题运算 + 结构图 ｜ 每节都能自己算一遍、跑一遍",
    "meta": [
        ("源课件", "L01_IntroductionToOS.pdf，72 页"),
        ("本讲口径", "先动手后讲理：每节以代码或例题运算为主线，理论只用来解释为什么这么算"),
        ("页码口径", "「课件 p.N」指源 PDF 的页序（共 72 页），不是幻灯片编号"),
        ("怎么读", "§1 站位图 → §2 一条命令走一趟 → §3 fork 与进程 → §4 系统调用判据 → §5 访存算例 → §6 磁盘算例 → §7 地图"),
        ("动手指令", "Windows 用 WSL 或 Linux 虚拟机；§2–§4 的代码在 WSL / Ubuntu 下原样可跑"),
        ("原文在哪", "CS340\\01_讲义\\L01_IntroductionToOS.pdf；本讲义只讲，不复制全文"),
    ],

    "sections": [
        {
            "no": "0", "zh": "本讲导读", "en": "How to Use This Handout",
            "lec": "这本不是「读一遍就懂」的讲义，是「做一遍才会」的：每节都给你一段能跑的代码或一道能算的题，理论只在算完之后用一句解释。",
            "body": [
                ("p", "<b>这一节能解决什么。</b>让你说清一件具体的事：你敲一条命令、跑一个程序时，操作系统到底替你做掉了哪些步骤。说清之后，后面八讲的调度、内存、文件系统才不是空词。"),
                ("p", "<b>这一节不能解决什么。</b>不教你怎么写内核模块，也不推导调度算法；本讲只给「看得见的手」——命令、代码、算例、结构图。"),
                ("p", "<b>每节的结构固定</b>：先给一段代码或一道算例 → 你跟着做/算 → 再用三五行解释它为什么是这样 → 需要时配一张结构图。"),
                ("note", "本讲地图", "站位（§1）→ 一条命令走一趟（§2）→ fork 与进程状态（§3）→ 系统调用怎么认（§4）→ 访存算例（§5）→ 磁盘算例（§6）→ 三大组件（§7）。"),
            ],
        },
        {
            "no": "1", "zh": "站位：一张图看懂谁夹在中间", "en": "Where the OS Sits",
            "lec": "先看结构图，再看一句话定义，最后用一张三列的表把「谁负责什么」压实；这节不需要计算，但图要能自己画出来。",
            "body": [
                ("svg", _LAYERS, "图 1　三层站位：用户 → 操作系统 → 硬件；中间那条线就是本讲后面要一直用到的接口"),
                ("q", "A program that acts as an intermediary between a user of a computer and the computer hardware.", "课件 p.4"),
                ("p", "把图翻成一句话：OS 是夹在用户和硬件之间的那层软件。注意两个箭头方向不同——往上给「好用的接口」（文件、进程、内存），往下做「具体的脏活」（设备、寄存器、扇区）。"),
                ("table", ["你在哪个位置", "能看到什么", "能直接做什么"],
                 [["用户（写程序的人）", "文件、进程、内存这些概念", "只能通过库函数或系统调用办事"],
                  ["操作系统（内核态）", "全部硬件与全部进程", "任何指令都能执行"],
                  ["硬件", "只有电平与指令", "不知道自己被谁用"]],
                 ["24%", "38%", "38%"]),
                ("eg", "把一页纸上的程序文件变成「屏幕上跑起来的窗口」，中间最少要跨哪几层？",
                 ["程序在磁盘上 → 被 OS 读进内存（这一步你不参与）",
                  "OS 为它建一个进程，分配内存与执行权",
                  "CPU 开始执行它的指令，输出通过 I/O 控制器送到屏幕"],
                 "答案：跨了三层——硬件（磁盘/CPU/显卡）、OS（装载与分配）、用户程序（指令）。你只写了第三层。"),
            ],
        },
        {
            "no": "2", "zh": "一条命令走一趟：ls 到底做了什么", "en": "Trace One Command",
            "lec": "这一节最能建立直觉：一条 ls 背后是 fork → exec → 系统调用 → 内核干活 → 回显。先跑命令看结果，再看结构图，最后用一道题确认你有没有记住顺序。",
            "body": [
                ("code", "shell", "ls -l\n# 输出示例（列含义）：\n-rw-r--r-- 1 ryoo ryoo 1024 Nov 16 10:02 notes.md\n# 权限  链接数 属主 属组 大小 修改时间 文件名", "在你的目录里跑一次，逐列对着看"),
                ("p", "你敲下回车后，shell（也是一个进程）做三件事：<b>fork</b> 出一个子进程 → 子进程 <b>exec</b> 成 ls → ls 通过系统调用读目录、写屏幕。三者里只有 fork 与 exec 是系统调用，ls 内部还要再调 readdir/write。"),
                ("svg", _SYSCALL, "图 2　一次系统调用的往返：用户态发请求 → 陷入内核 → 内核做事 → 回到用户态拿结果"),
                ("code", "bash", "# 亲眼看一次：用 strace 把系统调用逐条打出来（Linux / WSL）\nstrace -f -e trace=process,file ls -l /tmp 2>&1 | head -20\n# 你会看到 fork / execve / openat / getdents64 / write 依次出现", "这条命令是本讲的「证据机」：说得再漂亮，不如让系统自己打一遍"),
                ("eg", "一条 ls 至少经过几次「用户态 ↔ 内核态」的切换？",
                 ["fork：1 次（进内核建进程）",
                  "execve：1 次（进内核换程序）",
                  "openat / getdents64 / write：每条各 1 次，取决于目录里有多少项、写了几次屏幕",
                  "把 readdir 结果写屏通常 1 次 write 就够"],
                 "答案：命令本身 ≥3 次（fork、execve、至少一次 write），读目录还要再加。若改用库函数 printf 打印，printf 内部仍会调 write —— 所以「printf 不是系统调用、write 是」并不矛盾。"),
            ],
        },
        {
            "no": "3", "zh": "fork：返回值决定你是谁（附进程状态图）", "en": "fork and Process States",
            "lec": "这是全讲最该自己动手的一段。fork 只调一次却返回两次，返回值是唯一的身份区别；把三个小实验跑一遍，再算一道「打印几次」的题，这节就算过。",
            "body": [
                ("code", "c", "#include <stdio.h>\n#include <unistd.h>\n\nint main(void) {\n    pid_t p = fork();          /* 调用一次，返回两次 */\n    if (p < 0) { perror(\"fork\"); return 1; }\n    if (p == 0) printf(\"我是子进程，pid=%d\\n\", getpid());\n    else        printf(\"我是父进程，子进程 pid=%d\\n\", p);\n    return 0;\n}\n/* 编译：gcc f.c -o f   运行：./f */", "编译运行两遍，看输出顺序为什么有时不同"),
                ("p", "fork 之后有两个进程各跑一段：<b>父进程拿到子进程的 pid</b>（一个正数），<b>子进程拿到 0</b>，出错返回负数。靠这个返回值，同一段代码走了两个分支——这就是「一次调用、两次返回」的含义。课件 p.36 把这件事说得更准：进程是程序的「执行实例」，两个实例各自拥有独立的运行状态。"),
                ("eg", "下面这段代码打印几个 A？（这是考试最常见的 fork 计数题）\n\n    fork(); fork(); printf(\"A\");\n",
                 ["第 1 次 fork：1 个进程变 2 个（父 + 子）",
                  "第 2 次 fork：这 2 个进程各自再 fork 一次 → 2 × 2 = 4",
                  "每个进程都会执行到 printf，各自打印一次"],
                 "答案：4 个 A。规律是「连续 n 次 fork，进程数 = 2ⁿ」，printf 在最后则打印 2ⁿ 次；若 printf 夹在两次 fork 之间，就要按层数算。"),
                ("eg", "若把上面的代码改成：\n\n    printf(\"A\"); fork(); printf(\"B\");\n\nA 与 B 各打印几次？",
                 ["printf(\"A\") 在 fork 前，只有最初的 1 个进程执行 → A 打印 1 次",
                  "fork 后 2 个进程，各自执行 printf(\"B\") → B 打印 2 次"],
                 "答案：A 1 次、B 2 次。关键判据是「这一行在 fork 之前还是之后」。"),
                ("svg", _STATE, "图 3　进程状态迁移：就绪 ──调度──▶ 运行 ──等 I/O──▶ 阻塞 ──I/O 完成──▶ 就绪"),
                ("p", "fork 出来的子进程一开始处于<b>就绪</b>态，被调度器选中才进<b>运行</b>；一旦要等 I/O（比如读磁盘）就进<b>阻塞</b>，I/O 完成再回就绪。图 3 这张图后面 L02/L03 会反复用。"),
            ],
        },
        {
            "no": "4", "zh": "怎么判断一个函数是不是系统调用", "en": "System Call or Library Call",
            "lec": "这节给判据，不给定义。判据只有一条：它有没有跨进内核。用 strace 当场验，比背定义可靠。",
            "body": [
                ("code", "bash", "# 用 strace 同时看 printf 与 write 的差别\nstrace -e trace=write printf 'hello\\n' 2>&1 | head -5\n# 输出里出现 write(1, \"hello\\n\", 6) = 1\n# 也就是说：printf 自己不下内核，它内部的 write 才下", "printf 只是库函数，真正跨模式的是 write"),
                ("q", "System calls are the programming interface between processes and the OS kernel.", "课件 p.27"),
                ("table", ["对比项", "系统调用", "库函数"],
                 [["跑在哪", "内核态", "用户态"],
                  ["跨不跨模式", "跨，有保存/恢复现场的开销", "不跨，普通函数跳转"],
                  ["判据怎么验", "strace 里能看到这条调用", "strace 里看不到它，只能看到它内部调的系统调用"],
                  ["例子", "read、write、fork、execve、openat", "printf、strlen、malloc"]],
                 ["16%", "42%", "42%"]),
                ("eg", "判断：printf、strlen、malloc、write、getpid —— 哪几个是系统调用？",
                 ["printf：库函数，内部用 write 落地",
                  "strlen：纯用户态计算，不碰内核",
                  "malloc：库函数；当堆不够时它内部调 brk/mmap 向内核要内存",
                  "write、getpid：直接就是系统调用"],
                 "答案：只有 write、getpid 是系统调用。判据不是「能不能读写文件」，而是「有没有跨进内核」。"),
            ],
        },
        {
            "no": "5", "zh": "内存层次：算一次平均访存时间", "en": "Memory Hierarchy Worked Example",
            "lec": "这节要动笔算。层次图先看懂谁快谁慢，然后用命中率算平均访存时间——这类题考试必出，套公式之前先算清「每多一层加多少」。",
            "body": [
                ("svg", _MEMHIER, "图 4　存储层次：越往上越快越贵越少；OS 的活就是让常用数据尽量留在上面"),
                ("p", "常用数据要在上层，谁负责搬？课件 p.46 的反问很直接：你写程序时从没搬过这三层，搬的人是 OS。这张图就是内存管理那一讲的起点。"),
                ("eg", "L1 命中率 95%，命中耗时 1 ns；未命中则查 L2，L2 命中率 90%（在 L1 未命中的前提下），耗时 10 ns；再未命中查主存，耗时 100 ns。求平均访存时间 AMAT。",
                 ["先算「L1 未命中的代价」= L2 时间 + L2 也未命中的概率 × 主存时间 = 10 + 0.1 × 100 = 20 ns",
                  "再算加权：AMAT = 命中耗时 + 未命中率 × 未命中代价 = 1 + 0.05 × 20",
                  "= 1 + 1 = 2 ns"],
                 "答案：AMAT = 2.0 ns。注意 L2 的 90% 是「L1 未命中之后」的条件概率，不是全局；把条件搞错是这类题最常见的失分点。"),
                ("eg", "若把 L1 命中率从 95% 提到 99%，其他不变，AMAT 变成多少？",
                 ["AMAT = 1 + (1 − 0.99) × 20 = 1 + 0.01 × 20",
                  "= 1.2 ns"],
                 "答案：1.2 ns，比原来快 40%。这说明「提高一点命中率」的收益远大于「换更快的寄存器」——所以缓存在体系结构里才这么重要。"),
            ],
        },
        {
            "no": "6", "zh": "磁盘：算一次旋转延迟", "en": "Disk Rotational Latency",
            "lec": "这节把扇区、磁道换成数字。只记一个公式：一圈的时间 = 60 / 转速（秒），平均旋转延迟 = 半圈。",
            "body": [
                ("q", "One or more metal platters that rotate at a constant speed (e.g., 5400rpm, 7200 rpm, etc) … Each track is divided into sectors. A sector is like a slice of a pizza.", "课件 p.9"),
                ("eg", "一块 7200 rpm 的硬盘，平均旋转延迟是多少毫秒？",
                 ["转速 7200 转/分 → 每分钟 7200 圈 → 每圈 = 60 / 7200 s",
                  "60 / 7200 = 0.00833 s = 8.33 ms",
                  "平均旋转延迟 = 半圈 = 8.33 / 2"],
                 "答案：约 4.17 ms。5400 rpm 同理：60 / 5400 = 11.1 ms，半圈约 5.56 ms，比 7200 转慢约 1.4 ms。"),
                ("eg", "一次随机读要算哪三段延迟？各占多少（7200 rpm、寻道 8 ms、传输 0.1 ms）？",
                 ["① 寻道（seek）：把磁头移到目标磁道 ≈ 8 ms",
                  "② 旋转（rotational）：等目标扇区转到磁头下，平均半圈 ≈ 4.17 ms",
                  "③ 传输（transfer）：读完这一段数据 ≈ 0.1 ms"],
                 "答案：合计约 12.27 ms，而且花在「等」上的时间是传输的 120 倍。这就是为什么顺序读写比随机读写快得多，也是文件系统要尽量连续分配的原因。"),
            ],
        },
        {
            "no": "7", "zh": "三大组件：接下来八讲学什么", "en": "Three Components Ahead",
            "lec": "最后一节回到地图。每个组件配一句「你会算什么题」，这样后面听课才知道自己在做哪一类练习。",
            "body": [
                ("table", ["组件", "管什么", "后面你会算的题", "去哪一讲"],
                 [["进程", "执行权与运行现场", "fork 计数、调度顺序、周转时间", "L02 / L03"],
                  ["内存", "分配、搬移、回收", "AMAT、页面置换命中率", "L08 / L09"],
                  ["文件系统", "存储设备的组织方式", "空闲块管理、索引块寻址", "后续文件系统一讲"]],
                 ["12%", "26%", "36%", "26%"]),
                ("p", "三者的共同点：都在替用户保管并分配某种有限资源。区别只在于资源不同——CPU 时间、物理内存、磁盘空间（课件 p.34 就是这么分的）。"),
                ("eg", "一个作业里同时出现这四件事：「进程 A 被调度上 CPU」「进程 B 等磁盘读完」「C 的页被换出到磁盘」「新建了一个 300 KB 的文件」，分别归哪个组件？",
                 ["A 上 CPU → 进程管理（执行权分配）",
                  "B 等磁盘 → 进程管理判定阻塞，磁盘那边由 I/O 与文件系统接手",
                  "C 的页被换出 → 内存管理（缺页与置换）",
                  "新建文件 → 文件系统（目录条目 + 已分配空间）"],
                 "答案：前两件归进程，第三件归内存，第四件归文件系统。同一时刻三块都在动，这就是 OS 一屏多事的内情。"),
                ("note", "本讲到这里的判据", "你能不看讲义回答：fork 返回 0 的是谁？为什么 printf 不是系统调用？L1 命中率 95% 时 AMAT 是多少？三个都答得出，这讲就算过了。"),
            ],
        },
    ],

    "summary": {
        "no": "8", "zh": "本讲小结", "en": "Takeaways",
        "lec": "收口用一张表：每条都配一个可验证的动作或数字，方便回头复核。",
        "head": ["记住什么", "一句话", "怎么自查"],
        "head_widths": ["24%", "48%", "28%"],
        "rows": [
            ["站位", "OS 夹在用户与硬件之间", "画出图 1 三层"],
            ["一条命令", "fork → exec → 系统调用 → 内核干活", "strace 跑一次 ls"],
            ["fork 返回值", "父得子 pid，子得 0", "跑 §3 的 c 代码"],
            ["fork 计数", "连续 n 次 fork → 2ⁿ 个进程", "算 `fork();fork();printf(\"A\")` = 4 个 A"],
            ["系统调用判据", "看有没有跨进内核，不看能不能读写文件", "strace 里找得到就是"],
            ["AMAT", "命中时间 + 未命中率 × 未命中代价", "95% 命中、L1 1ns → 2.0 ns"],
            ["旋转延迟", "半圈时间 = 30 / 转速（秒）", "7200 rpm → 4.17 ms"],
        ],
        "tail": "如果只带走一句：<b>操作系统的每一件事，最后都能落到一段代码或一个算式上</b>；讲不出代码也列不出算式，就等于没懂。",
    },

    "quiz": {
        "no": "9", "zh": "自测", "en": "Self-check",
        "lec": "六题全是算或写，不考背诵。做不出来就回对应小节重跑一遍代码。",
        "items": [
            ("`fork(); fork(); fork(); printf(\"A\");` 打印几个 A？",
             "答：8 个（2³）。每次 fork 让进程数翻倍，最后的 printf 由全部进程各执行一次。回看 §3。"),
            ("父进程 fork 成功后拿到的返回值是什么？子进程拿到什么？",
             "答：父进程拿到子进程的 pid（正数），子进程拿到 0，失败返回负数。这也是同一段代码能分两条路走的原因。回看 §3。"),
            ("用一条命令证明 printf 不是系统调用，你会跑什么？",
             "答：`strace -e trace=write printf 'hi'` —— 输出里只有 write，没有 printf；printf 内部调的就是这个 write。回看 §4。"),
            ("L1 命中率 90%、L1 1 ns；未命中查 L2（命中率 80%、10 ns）；再未命中查主存 100 ns。求 AMAT。",
             "答：未命中代价 = 10 + 0.2 × 100 = 30 ns；AMAT = 1 + 0.1 × 30 = 4.0 ns。回看 §5。"),
            ("5400 rpm 硬盘的平均旋转延迟是多少？",
             "答：60 / 5400 = 11.1 ms 一圈，半圈约 5.56 ms。回看 §6。"),
            ("一条 `ls -l` 里，哪些动作是系统调用，哪些只是库函数？",
             "答：fork、execve、openat、getdents64、write 是系统调用；printf/puts 这类输出封装是库函数，内部再调 write。回看 §2、§4。"),
        ],
    },

    "glossary": {
        "no": "10", "zh": "术语表", "en": "Glossary",
        "lec": "本讲出现的术语，按首次出现顺序排；英文是课件原词，写代码查文档都用它。",
        "rows": [
            ("操作系统", "operating system (OS)", "课件 p.4", "夹在硬件与用户之间的一层软件"),
            ("中介", "intermediary", "课件 p.4", "课件描述 OS 位置的用词"),
            ("进程", "process", "课件 p.16、p.36", "程序的执行实例，有自己的运行状态"),
            ("系统调用", "system call", "课件 p.27", "进程与内核之间的编程接口，会跨模式"),
            ("内核态", "kernel mode", "课件 p.14", "可访问全部硬件、执行任何指令"),
            ("用户态", "user mode", "课件 p.14", "权限受限，普通程序与 shell 都在这里"),
            ("库函数", "library function", "课件 p.31", "用户态库里的函数，不跨进内核"),
            ("fork", "fork", "课件 p.16 上下文", "复制出一个子进程；父得子 pid，子得 0"),
            ("exec", "execve", "课件 p.16 上下文", "把当前进程换成另一个程序，pid 不变"),
            ("主存", "main memory", "课件 p.12", "CPU 直接寻址的内存，约 100 ns"),
            ("缓存", "cache", "课件 p.8", "CPU 与主存之间的小而快的存储"),
            ("命中率", "hit rate", "本讲 §5", "访问在上层被满足的比例"),
            ("平均访存时间", "AMAT", "本讲 §5", "命中时间 + 未命中率 × 未命中代价"),
            ("磁道", "track", "课件 p.9", "盘片上的同心圆"),
            ("扇区", "sector", "课件 p.9", "磁道切出来的一段，读写最小单位"),
            ("转速", "rpm", "课件 p.9", "每分钟转数；决定旋转延迟"),
            ("就绪", "ready", "本讲 §3", "可运行、等 CPU；被调度才进运行"),
            ("阻塞", "blocked", "本讲 §3", "等 I/O 或事件，给 CPU 也跑不了"),
            ("抽象", "abstraction", "课件 p.15", "把硬件细节藏起来、给出好用的概念"),
            ("资源管理者", "resource manager", "课件 p.32", "OS 的身份之一：管所有物理设备"),
        ],
    },

    "appendix": {
        "no": "11", "zh": "附录", "en": "Appendix",
        "lec": "一张算式速查加一组误解。算式那几条考试直接用，误解那几条是失分重灾区。",
        "symbols": [
            ["AMAT", "平均访存时间 = 命中时间 + 未命中率 × 未命中代价", "本讲 §5"],
            ["2ⁿ", "连续 n 次 fork 后的进程数", "本讲 §3"],
            ["60/rpm", "一圈的时间（秒）", "本讲 §6"],
            ["p.N", "源 PDF 第 N 页（不是幻灯片编号）", "本讲义口径"],
        ],
        "myths_title": "常见误解",
        "myths": [
            "以为 printf 是系统调用：它是库函数，跨进内核的是它内部调用的 write。",
            "把 fork 记成「调用两次」：其实只调用一次、返回两次，靠返回值分区。",
            "算 AMAT 时把 L2 的命中率当全局概率：它是「L1 未命中之后」的条件概率。",
            "把旋转延迟当成一整圈：平均值是半圈。",
            "以为程序一跑起来就是运行态：fork 出来先就绪，被调度才运行。",
        ],
    },

    "tail": [],
}
