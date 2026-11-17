# -*- coding: utf-8 -*-
"""品牌与成品标识的唯一出处（2026-11-17 用户：「PDF 下面加 AI 提示 + 项目地址 + 软件名」）。

为什么单独一个文件：页脚、界面脚注、README、更新提示都要这三样东西，
写死在各处就会有一天对不上（以前 README 说「页脚固定印着免责」，代码里其实没印）。
改这里一处，全仓（含 PDF 页脚）一起变。

判据（PRTS R105）：tools\\check\\check-pdf-brand.py 逐项比对「常量在 _brand.py 里」
「页脚真的印出来了」「链接可点」「深浅两种底都有对比度」。
"""

PRODUCT_NAME = "羽毛笔 La Pluma"                            # 软件名（页脚第二行左侧）
PROJECT_URL = "https://github.com/Charlotte0124/LaPluma"    # 项目地址（可点，真实 URI）
PROJECT_URL_TEXT = "github.com/Charlotte0124/LaPluma"       # 页脚显示用的短写
DISCLAIMER = "本内容由 AI 生成，仅供参考；重要信息请自行核实"   # 免责（整句，正常宽度用）
DISCLAIMER_SHORT = "AI 生成，仅供参考"                        # 免责（放不下时退成这句）
SEP = "·"
