# 规则引擎设计方案

## 1. 设计目标

规则引擎用于根据交易流水的特征自动执行分类、标记、商户标准化等操作，例如：

- 自动将包含“美团外卖”的流水归类为“餐饮美食”
- 自动将“信用卡还款”识别为“转账”
- 自动给大额消费添加标签
- 自动标准化商户名称
- 自动识别退款交易

推荐采用组合式设计，而不是单独使用某一种设计模式。

整体方案：

> **Specification + Composite + Command + Pipeline / Chain of Responsibility**

分别负责：

- **Specification**：判断一笔交易是否匹配条件
- **Composite**：实现 `AND / OR / NOT` 条件树
- **Command**：定义匹配后的动作
- **Pipeline / Chain of Responsibility**：控制多条规则的执行顺序

---

## 2. 规则数据结构

一条规则由以下部分组成：

```text
Rule
├── 基本信息
│   ├── name
│   ├── priority
│   ├── enabled
│   └── stop_processing
│
├── Conditions
│   └── 条件树
│
└── Actions
    └── 一个或多个动作
```

例如：

```json
{
  "name": "美团外卖归类餐饮",
  "priority": 100,
  "enabled": true,
  "conditions": {
    "and": [
      {
        "field": "merchant",
        "operator": "contains",
        "value": "美团外卖"
      },
      {
        "field": "amount",
        "operator": ">",
        "value": 0
      }
    ]
  },
  "actions": [
    {
      "type": "set_category",
      "value": "餐饮美食"
    },
    {
      "type": "add_tag",
      "value": "外卖"
    }
  ],
  "stop_processing": false
}
```

---

# 3. 条件系统

## 3.1 使用 Specification Pattern

条件本身不应该与具体业务逻辑绑定。

统一抽象成：

```text
Condition
├── field
├── operator
└── value
```

例如：

```text
merchant contains "美团"
```

```text
amount > 1000
```

```text
category = "电子产品"
```

---

## 3.2 支持 AND / OR / NOT

建议底层第一版就支持复杂条件树。

例如：

```text
商户包含 "京东"
AND
金额 > 1000
```

还可以进一步组合：

```text
商户包含 "支付宝"
AND
(
    描述包含 "盒马"
    OR
    描述包含 "叮咚买菜"
)
```

内部结构：

```text
AND
├── merchant contains "支付宝"
└── OR
    ├── description contains "盒马"
    └── description contains "叮咚买菜"
```

JSON：

```json
{
  "and": [
    {
      "field": "merchant",
      "operator": "contains",
      "value": "支付宝"
    },
    {
      "or": [
        {
          "field": "description",
          "operator": "contains",
          "value": "盒马"
        },
        {
          "field": "description",
          "operator": "contains",
          "value": "叮咚买菜"
        }
      ]
    }
  ]
}
```

---

## 3.3 推荐支持的条件运算符

第一阶段支持：

```text
equals
not_equals

contains
not_contains

starts_with
ends_with

>
>=
<
<=

between

is_empty
is_not_empty
```

第二阶段可增加：

```text
regex
in
not_in
```

---

# 4. 条件字段

推荐至少支持：

```text
merchant
description
amount
account
category
transaction_type
date
currency
payee
```

以后还可以增加：

```text
tags
owner
source
import_source
original_description
```

---

# 5. 动作系统

条件和动作必须完全解耦。

规则应该统一描述为：

```text
WHEN
    conditions

THEN
    actions
```

而不是设计大量固定规则类型，例如：

```text
MerchantCategoryRule
TransferRule
RefundRule
```

否则后期会越来越难扩展。

---

## 5.1 推荐动作

第一阶段支持：

```text
set_category
set_merchant
set_transaction_type
set_note

add_tag
remove_tag

set_owner

include_in_statistics
exclude_from_statistics
```

例如：

```text
WHEN
    merchant contains "美团"

THEN
    merchant = "美团"
    category = "餐饮美食"
    add_tag = "外卖"
```

一条规则可以同时执行多个动作。

---

# 6. 交易类型不要与分类混在一起

建议交易本身增加：

```text
transaction_type
```

例如：

```text
expense
income
transfer
refund
adjustment
```

不要把：

```text
信用卡还款
退款
转账
```

当成普通消费分类。

---

## 6.1 信用卡还款

例如：

```text
招商银行信用卡还款
-3000
```

如果把它当：

```text
支出 3000
```

就会造成消费统计重复。

正确处理：

```text
transaction_type = transfer
```

真实消费已经在信用卡刷卡时统计过。

---

## 6.2 退款

例如：

```text
美团退款
+68
```

建议：

```text
transaction_type = refund
```

而不是：

```text
income
```

否则收入统计会被污染。

---

# 7. 多规则执行

多个规则按照优先级进入 Pipeline。

例如：

```text
Transaction
    ↓
退款识别
    ↓
转账识别
    ↓
商户标准化
    ↓
自动分类
    ↓
标签规则
    ↓
完成
```

执行逻辑：

```python
for rule in rules:
    if not rule.enabled:
        continue

    if rule.matches(transaction):
        rule.apply(transaction)

        if rule.stop_processing:
            break
```

---

# 8. 一笔交易允许匹配多个规则

不建议默认：

```text
第一条规则匹配后立即停止
```

因为不同规则可能处理不同字段。

例如：

### Rule A

```text
WHEN
merchant contains "美团"

THEN
category = 餐饮
tag += 外卖
```

### Rule B

```text
WHEN
amount > 100

THEN
tag += 大额消费
```

最终结果：

```text
美团外卖 ¥128

分类：
餐饮

标签：
- 外卖
- 大额消费
```

---

# 9. 规则优先级

每条规则增加：

```text
priority
```

推荐：

> 数字越小，优先级越高。

例如：

```text
10      特殊修正规则
100     转账 / 退款识别
200     商户规则
500     分类规则
1000    默认规则
```

执行：

```sql
ORDER BY priority ASC
```

---

# 10. Stop Processing

每条规则可以设置：

```text
stop_processing = true / false
```

例如：

```text
WHEN
description contains "信用卡还款"

THEN
transaction_type = transfer

STOP PROCESSING
```

这样可以避免后续规则再次错误处理。

---

# 11. 字段级锁定

未来可以增加高级功能：

```text
lock_fields
```

例如：

```text
Rule 1

京东白条还款
→ transaction_type = transfer

lock:
transaction_type
```

后续规则：

```text
京东
→ merchant = 京东
→ category = 购物
```

仍然可以修改：

```text
merchant
category
```

但不能再修改：

```text
transaction_type
```

第一版 UI 可以不做，但底层数据模型可以预留。

---

# 12. 规则执行时机

推荐支持三种执行方式。

## 12.1 导入时自动执行

账单导入流程：

```text
Parse
  ↓
Normalize
  ↓
Deduplicate
  ↓
Rule Engine
  ↓
Save
```

交易进入系统时立即执行规则。

---

## 12.2 手动执行

用户可以选择：

```text
运行全部规则
```

或者：

```text
运行当前规则
```

---

## 12.3 历史回溯

必须支持 Retroactive Run。

用户创建或修改规则后：

```text
发现该规则可以匹配 2381 条历史交易。

[预览影响]
[应用到历史交易]
[仅应用未来交易]
```

---

# 13. 历史回溯必须支持 Dry Run

不建议用户点击后直接修改数据库。

应该先提供：

```text
Preview / Dry Run
```

例如：

```text
规则：

merchant contains "美团"

动作：

category → 餐饮美食
```

预览：

```text
匹配交易：
2381

即将修改：
2012 条：未分类 → 餐饮美食
231 条：购物 → 餐饮美食
138 条：其他 → 餐饮美食
```

并显示若干示例交易。

例如：

```text
2026-09-20
美团外卖
¥35
当前：未分类
修改后：餐饮美食
```

这样可以显著降低误操作风险。

---

# 14. 历史回溯采用异步任务

历史流水可能有：

```text
10 万+
100 万+
```

不应该在 HTTP 请求中同步完成。

推荐：

```text
POST /rules/:id/run
```

然后创建：

```text
RuleRunJob
```

例如：

```text
RuleRun
├── id
├── rule_id
├── status
├── total
├── processed
├── matched
├── modified
├── started_at
└── finished_at
```

前端显示：

```text
正在执行规则

34,230 / 112,394

匹配：
18,391

修改：
17,942
```

---

# 15. 记录字段修改来源

这是规则系统里非常重要的一点。

建议字段保存修改来源。

例如：

```text
category_id = 3

category_source = rule

category_rule_id = 123
```

来源可以是：

```text
manual
import
rule
system
```

---

## 15.1 手动修改优先

例如规则自动判断：

```text
美团
→ 餐饮
```

用户后来手动修改为：

```text
工作报销
```

后续再次执行规则时，不应该默认覆盖用户操作。

可以增加规则选项：

```text
☐ 覆盖用户手动修改的字段
```

默认关闭。

也就是说：

```text
manual > rule > import
```

---

# 16. 冲突处理

例如：

### Rule A

```text
priority = 100

美团
→ category = 餐饮
```

### Rule B

```text
priority = 50

description contains "公司"
→ category = 工作报销
```

交易：

```text
美团外卖
公司加班餐
```

两个规则都会命中。

因此需要明确：

```text
priority
stop_processing
字段锁定
manual override
```

共同决定最终结果。

---

# 17. 推荐架构

整体结构：

```text
                    Transaction
                         │
                         ↓
                    Rule Engine
                         │
                         ↓
               按 priority 排序
                         │
                         ↓
              Specification Evaluator
                         │
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
         AND             OR             NOT
          │
          ↓
       Condition
          │
   ┌──────┼────────┐
   ↓      ↓        ↓
contains equals  between
          │
          ↓
        Match?
          │
          ↓
     Action Executor
          │
 ┌────────┼──────────┐
 ↓        ↓          ↓
Category Merchant   Tags
 ↓
Transaction Type
          │
          ↓
 Continue / Stop
          │
          ↓
       Next Rule
```

---

# 18. 代码结构

推荐：

```text
Rule
│
├── ConditionGroup
│   │
│   ├── Condition
│   ├── Condition
│   │
│   └── ConditionGroup
│
└── Actions
    │
    ├── SetCategoryAction
    ├── SetMerchantAction
    ├── SetTransactionTypeAction
    ├── AddTagAction
    └── SetNoteAction
```

对应设计模式：

| 模块 | 设计模式 |
|---|---|
| Condition | Specification |
| ConditionGroup | Composite |
| Action | Command |
| Rule Engine | Pipeline / Chain of Responsibility |

---

# 19. 第一阶段推荐功能

## 条件

```text
✅ equals
✅ not_equals

✅ contains
✅ not_contains

✅ >
✅ <
✅ >=
✅ <=

✅ between

✅ is_empty
✅ is_not_empty

✅ AND
✅ OR
```

---

## 条件字段

```text
✅ merchant
✅ description
✅ amount
✅ account
✅ category
✅ transaction_type
```

---

## 动作

```text
✅ 设置分类
✅ 设置商户
✅ 添加标签
✅ 删除标签
✅ 修改备注
✅ 标记 transfer
✅ 标记 refund
✅ 是否计入统计
```

---

## 执行控制

```text
✅ priority

✅ continue
✅ stop

✅ 导入时自动执行
✅ 手动执行

✅ 历史回溯
✅ Dry Run / Preview
```

---

# 20. 第二阶段功能

后续再增加：

```text
NOT

Regex

字段锁定

规则分组

批量启用 / 禁用

规则复制

规则导入 / 导出

规则运行日志

命中次数统计

规则调试器

高级退款匹配

转账双边自动配对
```

---

# 最终建议

规则引擎不建议只选择：

> 责任链模式

或者：

> Specification Pattern

而应该组合使用：

```text
Specification
+
Composite
+
Command
+
Pipeline / Chain of Responsibility
```

核心思想：

```text
Conditions
决定
“什么时候执行”

Actions
决定
“执行什么”

Priority / Pipeline
决定
“按什么顺序执行”
```

建议从第一版开始支持：

```text
AND / OR

多 Action

Priority

Continue / Stop

历史回溯

Dry Run
```

历史回溯尤其不应该直接修改历史数据，而应该采用：

```text
Preview
    ↓
确认
    ↓
异步执行
    ↓
运行日志
```

这样既能覆盖当前简单的自动分类需求，又可以自然扩展到：

- 商户标准化
- 退款识别
- 信用卡还款
- 转账识别
- 家庭成员交易归属
- 标签自动化
- 历史账单清洗
- 智能分类