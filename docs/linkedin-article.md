# The Token Economics of Agentic AI: Programmatic Tool Calling and Prompt Caching in Practice

*Lessons from a working insurance claims agent built with Claude on Microsoft Foundry*

## Introduction

As enterprises move agentic AI from pilots to production, a new line item is getting attention: **token cost**. The price per token matters, but what really drives the bill is **how many tokens an agent burns to finish one task**. An agent that calls many tools, or pulls back large records, can be several times more expensive than it needs to be.

This article looks at two techniques that attack that cost directly: **programmatic tool calling** and **prompt caching**. I tested both with Claude models on Microsoft Foundry, using a realistic claims-handling agent. I share what they are, where they help, and where they do not.

## Where the tokens go in a traditional agent

In a typical agent, the model sits in the middle of every step. It asks for a tool, the application runs it, and the full result goes back to the model, which decides what to do next. Each of those round trips **re-sends the entire conversation**: the instructions, the tool descriptions, and every earlier result.

So the cost compounds. Five tool calls mean several model round trips, each re-reading everything before it. And if one tool returns a large record, say a ticket with dozens of fields the agent never needed, that bulk is re-read again and again. The model is doing clerical work (passing data along) at premium prices.

## Programmatic tool calling: let the model write the plan once

Anthropic's Claude models support a feature called **programmatic tool calling**. Instead of handling every tool call itself, the model delegates the whole sequence to a secure **sandbox container**:

1. The application sends the request to Claude through the **Claude Messages API**, along with the tools it can use and a flag saying those tools may be called from code.
2. Claude **writes one short program** that describes the whole job.
3. The program runs in the sandbox. Each time it needs data, it pauses and sends a **tool instruction back to the client application**.
4. The client application calls the real system (database, ticketing, email) with its own credentials and returns the result to the program in the sandbox. The sandbox never touches your systems or secrets.
5. The program filters, joins and applies the business rules by itself, then prints a small summary.
6. Only now is the model brought back into the loop, to **read that summary and compose the final answer**.

The raw data never passes through the model. It sees the plan and the conclusion, not the clutter in between.

**Availability note:** at the time of writing, on Microsoft Foundry this feature is supported for Claude deployments **hosted by Anthropic**. The deployment is created in Foundry, but the model runs on Anthropic's service. Claude models hosted on Azure do not support it yet. The demo uses Claude Haiku 5.5 deployed that way.

*[Insert the architecture diagram here: traditional vs programmatic tool calling]*

## The use case: a claims agent

The scenario is a health-insurance agent. A customer asks for an update on their claims. Claims live in **Azure SQL Database**, grievances are tracked in **Jira**, and **Microsoft 365 (through WorkIQ)** handles email.

The agent retrieves the customer's claims and any grievances they have raised. It then shortlists the denied claims whose grievance has **nobody assigned** to take it to closure, and sends an escalation email through WorkIQ to the designated person, asking for intervention. Finally, it replies to the customer with a **consolidated view of every claim**: which are paid, which are pending, and for denied ones, who is handling the grievance or that it has been escalated.

That is five tool calls. With programmatic tool calling, the sandbox program issued them in three batches. The client application ran each batch against the real systems and returned the results. The model wrote the program and the final answer, and nothing else.

## What we saw

With Jira returning its full record, as a real integration would, the same question cost:

- **About 27,500 tokens in four model calls** the traditional way
- **About 14,300 tokens in two model calls** with programmatic tool calling

That is **roughly half**, with the same correct answers. The saving comes from the large Jira records staying inside the sandbox instead of being re-read by the model at every step.

## The catch: setup has a cost

Programmatic tool calling is not free. To make it work, each request carries extra instructions that teach the model how to use the sandbox and how to write code against your tools. The model then spends output tokens writing the program. In our measurements this added **roughly 3,700 tokens to every model call**, before any real work began.

That is why it does not make sense for simple jobs. With only one or two tool calls, or with small results, the overhead cancels the saving. When we trimmed the Jira records to a handful of fields, the two approaches came out about even (roughly 12,000 against 12,700 tokens).

It pays off when there are **many tool calls, heavy payloads, or chains where each step depends on the last**. It also did not make our run faster: the pauses between the sandbox and the client add time.

## For Foundry native models: CodeAct

Customers building on Foundry native models and solutions can look at **CodeAct in Microsoft Agent Framework**. It applies the same idea: the model writes one program, which runs in an isolated sandbox, and the tools are called from inside it. Microsoft reports roughly 50% lower latency and over 60% fewer tokens on representative workloads.

It is still in **alpha**, so it is not yet a candidate for production-scale deployments.

## Prompt caching: pay less for what is repeated

Prompt caching is not new. I bring it up because this use case benefited from it.

The model reads the whole prompt on every call. With caching, the service stores the already-processed beginning of a prompt. A later request that starts with exactly the same content reads it from the cache at a much lower price. The cache lasts about five minutes and is refreshed each time it is used.

You turn it on by adding **one field to the request**, a cache control setting. (It is a field in the request body, not an HTTP header.) The real design work is in the payload: **put the static content first**, meaning tool definitions, instructions and reference material, and the parts that change **last**, such as the user's question and the conversation so far. Anything that varies near the start, like a timestamp, breaks the match.

Caching does not reduce the number of tokens. It reduces the **price** of the repeated ones. On a repeat request, about **65%** of the input in the traditional run and about **88%** in the programmatic run came from the cache. At typical list-price ratios (cached reads at about a tenth of normal input, and a small premium to write the cache), that is an estimated **40 to 46 percent lower cost** than the same run without caching. The first run, which has to write the cache, saved less, around 15 to 35 percent. These ratios are assumptions, so check them against your own pricing.

## Summary

- In a traditional agent, every tool result flows back through the model and is re-read at each step. Cost grows with the number of calls and the size of the data.
- **Programmatic tool calling** lets the model write one program that runs in a sandbox, while the client application makes the real tool calls. The model sees only the final summary.
- In our claims scenario it used **about half the tokens** (about 14,300 against 27,500) with the same answers.
- It carries a fixed overhead of roughly 3,700 tokens per model call, so it is **not worth it for one or two tool calls** or small payloads.
- **Prompt caching** is a separate, complementary lever: put static content first and repeated input becomes much cheaper. We estimate 40 to 46 percent lower cost on repeat runs.
- Results are from single runs of one scenario, and models vary from run to run. Treat them as directional and measure your own workload.

## What to do next

If you sponsor or run agentic AI programs, ask your teams three questions:

1. How many tool calls does a typical task make?
2. How large are the results those tools return?
3. Is anything static being re-sent, and re-billed, on every call?

Chains of many calls and heavy payloads are the best candidates for programmatic tool calling, and almost any agent with a stable prompt prefix can use caching. Pick one high-volume agent, measure its tokens before and after, and let the numbers decide.

The full demo, with the code and token breakdowns, is open source. I would be glad to hear what you find on your own workloads.

## References

- [Programmatic tool calling, Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/programmatic-tool-calling#how-programmatic-tool-calling-works)
- [Features overview (tool infrastructure), Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/overview#tool-infrastructure)
- [CodeAct in Agent Framework: Faster Agents with Fewer Model Turns, Microsoft Agent Framework](https://devblogs.microsoft.com/agent-framework/codeact-with-hyperlight/)
- [Demo application on GitHub: Claude-Foundry-Programmtic-Tool-Calling](https://github.com/MSFT-Innovation-Hub-India/Claude-Foundry-Programmtic-Tool-Calling)

#TokenEconomics #AgenticAI #AIAgents #ClaudeAI #Anthropic #MicrosoftFoundry #AzureAI #PromptCaching #GenerativeAI #AIStrategy #CostOptimization
