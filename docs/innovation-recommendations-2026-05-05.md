# LLM Research Innovation Recommendations — 2026-05-05

> Daily cron research run. Focus: LLM-as-judge, prompt evaluation rubrics, hallucination detection, CoT faithfulness, self-consistency, reward model calibration.

---

## New Papers Found (17 papers, all NEW DOIs)

### Category: LLM-as-Judge

| DOI | Title | Authors | Year | Venue |
|-----|-------|---------|------|-------|
| 10.48550/arxiv.2510.18196 | Contrastive Decoding Mitigates Score Range Bias in LLM-as-a-Judge | Fujinuma | 2025 | arXiv |
| 10.48550/arxiv.2511.04478 | Generate, Evaluate, Iterate: Synthetic Data for Human-in-the-Loop Refinement of LLM Judges | Do et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.09738 | Judge's Verdict: A Comprehensive Analysis of LLM Judge Capability Through Human Agreement | Han et al. | 2025 | arXiv |
| 10.48550/arxiv.2511.21140 | How to Correctly Report LLM-as-a-Judge Evaluations | Lee et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.08120 | Interpreting LLM-as-a-Judge Policies via Verifiable Global Explanations | Gajcin et al. | 2025 | arXiv |
| 10.1101/2025.04.22.25326219 | Automating Evaluation of AI Text Generation in Healthcare with LLM-as-a-Judge | Croxford et al. | 2025 | medRxiv |

### Category: Prompt Evaluation / Rubric-Based Scoring

| DOI | Title | Authors | Year | Venue |
|-----|-------|---------|------|-------|
| 10.48550/arxiv.2510.09030 | Automated Refinement of Essay Scoring Rubrics via Reflect-and-Revise | Harada et al. | 2025 | arXiv |
| 10.48550/arxiv.2511.20836 | Structured Prompting Enables More Robust, Holistic Evaluation of Language Models | Aali et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.01146 | mR3: Multilingual Rubric-Agnostic Reward Reasoning Models | Anugraha et al. | 2025 | arXiv |

### Category: Hallucination Detection

| DOI | Title | Authors | Year | Venue |
|-----|-------|---------|------|-------|
| 10.48550/arxiv.2510.10539 | Detecting Hallucinations in Authentic LLM-Human Interactions | Ren et al. | 2025 | arXiv |
| 10.48550/arxiv.2511.11087 | Can LLMs Detect Their Own Hallucinations? | Kadotani et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.19507 | Teaming LLMs to Detect and Mitigate Hallucinations | Till et al. | 2025 | arXiv |
| 10.48550/arxiv.2511.12236 | Consistency Is the Key: Detecting Hallucinations via Key Fact Inconsistencies | Gupta et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.00296 | Beyond Token Probes: Hallucination Detection via Activation Tensors with ACT-ViT | Bar-Shalom et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.16549 | ReviewGuard: Enhancing Deficient Peer Review Detection via LLM-Driven Data Augmentation | Zhang et al. | 2025 | arXiv |

### Category: CoT Faithfulness

| DOI | Title | Authors | Year | Venue |
|-----|-------|---------|------|-------|
| 10.48550/arxiv.2510.04040 | FaithCoT-Bench: Benchmarking Instance-Level Faithfulness of Chain-of-Thought Reasoning | Shen et al. | 2025 | arXiv |

### Category: Reward Model Calibration

| DOI | Title | Authors | Year | Venue |
|-----|-------|---------|------|-------|
| 10.48550/arxiv.2510.07743 | OpenRubrics: Towards Scalable Synthetic Rubric Generation for Reward Modeling | Liu et al. | 2025 | arXiv |
| 10.48550/arxiv.2510.00263 | Judging with Confidence: Calibrating Autoraters to Preference Distributions | Li et al. | 2025 | arXiv |
| 10.48550/arxiv.2511.12464 | Probing Preference Representations: Multi-Dimensional Evaluation of Reward Models | Wang et al. | 2025 | arXiv |

---

## Paper Summaries

### 1. Contrastive Decoding Mitigates Score Range Bias in LLM-as-a-Judge
**DOI**: 10.48550/arxiv.2510.18196  
**Abstract snippet**: LLM judge outputs are highly sensitive to pre-defined score ranges. Contrastive decoding achieves up to 11.3% relative improvement in Spearman correlation with human judgments across different score ranges.  
**PR Agent Relevance**: Score range bias directly affects review severity classification. Applying contrastive decoding to the judge step could improve consistency of `critical/high/medium/low` severity labels.

### 2. Generate, Evaluate, Iterate: Synthetic Data for Human-in-the-Loop Refinement of LLM Judges
**DOI**: 10.48550/arxiv.2511.04478  
**Abstract snippet**: Integrates synthetic data generation into the LLM-as-a-judge workflow, enabling users to create tailored test cases with configurable domains, personas, and desired outcomes. 83% of participants preferred it over manual creation.  
**PR Agent Relevance**: A tool for generating diverse synthetic PR review test cases (edge cases, borderline security findings) to continuously refine the judge's criteria without labeling overhead.

### 3. Judge's Verdict: A Comprehensive Analysis of LLM Judge Capability Through Human Agreement
**DOI**: 10.48550/arxiv.2510.09738  
**Abstract snippet**: Two-step methodology evaluating 54 LLMs as judges. Shows correlation alone is insufficient; introduces a "Turing Test for judges" based on agreement patterns. 23 models exhibit human-like patterns.  
**PR Agent Relevance**: Provides a principled framework for selecting which model to use as a critic/judge for PR review outputs, showing size ≠ quality for judging roles.

### 4. How to Correctly Report LLM-as-a-Judge Evaluations
**DOI**: 10.48550/arxiv.2511.21140  
**Abstract snippet**: Presents a plug-in framework correcting bias and constructing confidence intervals reflecting uncertainty from both test and calibration data. Introduces adaptive algorithm for efficient calibration sample allocation.  
**PR Agent Relevance**: Essential methodology for building statistically sound evaluation pipelines for the review agent — enables CI-reportable quality metrics with proper uncertainty estimates.

### 5. Interpreting LLM-as-a-Judge Policies via Verifiable Global Explanations
**DOI**: 10.48550/arxiv.2510.08120  
**Abstract snippet**: CLoVE extracts contrastive local explanations; GloVE condenses into a global policy. Evaluated on 7 harm detection benchmarks, global policies are highly faithful to LLM-as-a-Judge decisions.  
**PR Agent Relevance**: Extracting a global "judge policy" from the review agent's evaluation behavior would make finding severity assignments auditable and explainable to developers.

### 6. Automating Evaluation of AI Text Generation in Healthcare with LLM-as-a-Judge
**DOI**: 10.1101/2025.04.22.25326219  
**Abstract snippet**: Validates LLM-as-a-Judge against a structured rubric (PDSQI-9). GPT-o3-mini achieves ICC=0.818 with human evaluators. Reasoning models outperform non-reasoning models on rubric-based eval.  
**PR Agent Relevance**: Confirms that structured rubric-based LLM judges achieve near-human reliability; reasoning models (o3-mini, o4-mini) are preferred for rubric evaluation tasks like code review.

### 7. Automated Refinement of Essay Scoring Rubrics via Reflect-and-Revise
**DOI**: 10.48550/arxiv.2510.09030  
**Abstract snippet**: Iteratively refines rubrics by reflecting on scoring rationales vs. human score discrepancies. Achieves QWK improvements of up to 0.47 even starting from a simple initial rubric.  
**PR Agent Relevance**: The reflect-and-revise loop is directly applicable to PR review rubrics — the agent can compare its scoring rationale against accepted/rejected human decisions to self-improve rubric criteria.

### 8. Structured Prompting Enables More Robust, Holistic Evaluation of Language Models
**DOI**: 10.48550/arxiv.2511.20836  
**Abstract snippet**: DSPy+HELM integration. Without structured prompting, HELM underestimates LM performance by 4% on average. CoT reduces sensitivity to prompt design.  
**PR Agent Relevance**: Using DSPy-style structured prompting for review evaluation would improve benchmark stability and reduce variance in automated review quality measurements.

### 9. mR3: Multilingual Rubric-Agnostic Reward Reasoning Models
**DOI**: 10.48550/arxiv.2510.01146  
**Abstract snippet**: Trained on 72 languages; rubric-agnostic. Surpasses GPT-OSS-120B while 9× smaller. Rubrics are provided per-task rather than baked into the model.  
**PR Agent Relevance**: A rubric-agnostic reward model that accepts task-specific rubrics could evaluate different PR dimensions (security, correctness, style) with a single model by swapping rubric text.

### 10. Detecting Hallucinations in Authentic LLM-Human Interactions
**DOI**: 10.48550/arxiv.2510.10539  
**Abstract snippet**: AuthenHallu: first benchmark from real LLM-human dialogues. 31.4% hallucination rate overall; 60% in Math/Number domains. Vanilla LLM detectors are insufficient in real-world settings.  
**PR Agent Relevance**: Establishes baseline hallucination rates for LLMs in real interactions; PR review agents generating claims about code should assume ~30% of factual statements need verification.

### 11. Can LLMs Detect Their Own Hallucinations?
**DOI**: 10.48550/arxiv.2511.11087  
**Abstract snippet**: Using Chain-of-Thought, GPT-3.5 Turbo detects 58.2% of its own hallucinations. LLMs with CoT can detect hallucinations if sufficient knowledge is in their parameters.  
**PR Agent Relevance**: Self-hallucination detection via CoT is feasible but limited to ~58%; suggests adding a self-check pass for code claims is worthwhile but not sufficient alone — external verification still needed.

### 12. Teaming LLMs to Detect and Mitigate Hallucinations
**DOI**: 10.48550/arxiv.2510.19507  
**Abstract snippet**: Combining multiple LLMs with different training data and architectures substantially improves hallucination detection beyond single-model consistency methods, often with reduced inference costs.  
**PR Agent Relevance**: Multi-model consortium consistency for PR review output verification — using two different model families (e.g., Claude + Gemini) to cross-validate security findings reduces false positives.

### 13. Consistency Is the Key: Detecting Hallucinations via Key Fact Inconsistencies
**DOI**: 10.48550/arxiv.2511.12236  
**Abstract snippet**: CONFACTCHECK: responses to factual probes should be consistent within and across LLMs. Achieves higher accuracy with fewer API calls than existing baselines.  
**PR Agent Relevance**: Probing factual claims in PR review findings (e.g., "this function has no null check") with targeted consistency queries provides a lightweight hallucination guard without external knowledge bases.

### 14. Beyond Token Probes: Hallucination Detection via Activation Tensors with ACT-ViT
**DOI**: 10.48550/arxiv.2510.00296  
**Abstract snippet**: Vision Transformer applied to activation tensors across layers×tokens. Outperforms probing techniques, supports multi-LLM training, achieves strong zero-shot performance.  
**PR Agent Relevance**: For white-box model access scenarios, activation-based hallucination detection could flag unreliable code review claims before they become posted comments.

### 15. ReviewGuard: Enhancing Deficient Peer Review Detection via LLM-Driven Data Augmentation
**DOI**: 10.48550/arxiv.2510.16549  
**Abstract snippet**: Detects deficient reviews in academic peer review. Deficient reviews show lower structural complexity, higher self-reported confidence, and a higher proportion of negative sentiment. LLM-augmented training improves recall from 0.55 to 0.67.  
**PR Agent Relevance**: Directly transferable: detect when the review agent produces a "deficient" PR review (superficial, low-evidence, high-confidence-but-wrong findings) and trigger a re-review pass.

### 16. FaithCoT-Bench: Benchmarking Instance-Level Faithfulness of Chain-of-Thought Reasoning
**DOI**: 10.48550/arxiv.2510.04040  
**Abstract snippet**: First benchmark for instance-level CoT unfaithfulness detection. Over 1,000 trajectories with 300+ unfaithful instances with step-level evidence. Harder models produce more deceptively plausible but unfaithful CoT.  
**PR Agent Relevance**: CoT reasoning in PR review (the agent's rationale for a finding) may be unfaithful — this benchmark provides detection methods (counterfactual, logit-based, LLM-as-judge) applicable to review trace auditing.

### 17. OpenRubrics: Towards Scalable Synthetic Rubric Generation for Reward Modeling
**DOI**: 10.48550/arxiv.2510.07743  
**Abstract snippet**: Contrastive Rubric Generation (CRG) derives hard rules and principles by contrasting preferred vs. rejected responses. Rubric-RM surpasses size-matched baselines by 6.8% on RewardBench.  
**PR Agent Relevance**: Generating rubrics by contrasting accepted vs. rejected PR review comments (from developer feedback) could produce discriminative PR-specific reward signals without manual rubric writing.

### 18. Judging with Confidence: Calibrating Autoraters to Preference Distributions
**DOI**: 10.48550/arxiv.2510.00263  
**Abstract snippet**: Proposes calibrating probabilistic autoraters to target preference distributions. Verbalized probability predictions with improved calibration and significantly lower positional bias.  
**PR Agent Relevance**: Calibrating the review agent's severity judgments to match developer acceptance distributions would reduce the systematic over-/under-severity bias observed in deployed agents.

### 19. Probing Preference Representations: Multi-Dimensional Evaluation of Reward Models
**DOI**: 10.48550/arxiv.2511.12464  
**Abstract snippet**: MRMBench: six probing tasks for different preference dimensions. Reward models often struggle with multiple preference dimensions simultaneously. Inference-time probing provides confidence metric.  
**PR Agent Relevance**: PR reviews have multiple dimensions (security, correctness, style, performance). A multi-dimensional reward model that separately probes each dimension would provide more granular feedback quality signals.

---

## Innovation Recommendations (sorted: Impact↓ Innovation↓ Difficulty↑)

### 1. Calibrated Severity Autorater with Distribution Matching
**Recommendation**: Calibrated Severity Autorater with Distribution Matching  
**Papers**: "Judging with Confidence" (10.48550/arxiv.2510.00263) + "How to Correctly Report LLM-as-a-Judge Evaluations" (10.48550/arxiv.2511.21140)  
**Impact**: high  
**Innovation**: high  
**Difficulty**: med  
**Description**: The review agent's severity labels (critical/high/medium/low) have systematic bias — some severity levels are overrepresented relative to developer acceptance. Use distribution-matching fine-tuning (SFT or RL) on historical PR feedback to calibrate the autorater's probability predictions to match the actual target distribution of developer-accepted findings. Combine with the bias-corrected confidence interval framework to produce statistically sound severity reports. Output: each finding includes a calibrated confidence score, and the CI of the accuracy estimate is reported in evaluation runs.

---

### 2. Contrastive Rubric Generation from Developer Feedback
**Recommendation**: Contrastive Rubric Generation from Developer Feedback  
**Papers**: "OpenRubrics" (10.48550/arxiv.2510.07743) + "Automated Refinement of Essay Scoring Rubrics" (10.48550/arxiv.2510.09030)  
**Impact**: high  
**Innovation**: high  
**Difficulty**: med  
**Description**: Apply Contrastive Rubric Generation (CRG) to mine the PR review history: for each accepted vs. rejected review comment pair, contrast the two to derive hard rules ("never flag X without Y evidence") and implicit principles ("correctness findings must cite specific line numbers"). Run this weekly via a background job. Then use Reflect-and-Revise to iteratively refine the rubric by comparing the agent's scoring rationale against the historical human acceptance decisions. The resulting rubric is injected into the system prompt and becomes the agent's scoring contract.

---

### 3. Deficient Review Detector — Auto-Retry Gate
**Recommendation**: Deficient Review Detector — Auto-Retry Gate  
**Papers**: "ReviewGuard" (10.48550/arxiv.2510.16549) + "Probing Preference Representations" (10.48550/arxiv.2511.12464)  
**Impact**: high  
**Innovation**: high  
**Difficulty**: low  
**Description**: Adapt the ReviewGuard approach: train a lightweight classifier on features of PR review outputs — structural complexity (number of distinct reasoning steps), confidence-claim ratio (finding confidence vs. evidence density), and sentiment polarity per finding. A deficient review is one that is superficial, over-confident without evidence, or monotonically negative. The classifier triggers an automatic re-review pass with a higher CoT temperature and explicit evidence-requirement instruction. Also apply multi-dimensional preference probing to evaluate the review across security/correctness/style dimensions independently rather than as one scalar quality score.

---

## Appendix: JSON Format

```json
[
  {
    "doi": "10.48550/arxiv.2510.18196",
    "title": "Contrastive Decoding Mitigates Score Range Bias in LLM-as-a-Judge",
    "authors": "Yoshinari Fujinuma",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "LLM judge outputs are highly sensitive to pre-defined score ranges. Contrastive decoding achieves up to 11.3% relative improvement in Spearman correlation with human judgments.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Score range bias affects review severity classification. Contrastive decoding could improve consistency of critical/high/medium/low labels."
  },
  {
    "doi": "10.48550/arxiv.2511.04478",
    "title": "Generate, Evaluate, Iterate: Synthetic Data for Human-in-the-Loop Refinement of LLM Judges",
    "authors": "Hyo Jin Do, Zahra Ashktorab, Jasmina Gajcin",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Integrates synthetic data generation into LLM-as-a-judge workflows with configurable domains, personas, and desired outcomes. 83% preferred it over manual test case creation.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Enables generation of diverse synthetic PR review edge cases to continuously refine judge criteria without labeling overhead."
  },
  {
    "doi": "10.48550/arxiv.2510.09738",
    "title": "Judge's Verdict: A Comprehensive Analysis of LLM Judge Capability Through Human Agreement",
    "authors": "Steve Han, Gilberto Titericz Junior, Tom Balough",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Two-step methodology evaluating 54 LLMs as judges using Cohen's Kappa. Shows correlation alone is insufficient; introduces a 'Turing Test for judges' based on agreement patterns.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Provides a principled framework for selecting which model to use as a critic/judge for PR review outputs, showing model size ≠ quality for judging."
  },
  {
    "doi": "10.48550/arxiv.2511.21140",
    "title": "How to Correctly Report LLM-as-a-Judge Evaluations",
    "authors": "Chungpa Lee, Thomas Zeng, Jongwon Jeong",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Plug-in framework correcting LLM-judge bias and constructing confidence intervals reflecting uncertainty from both test and calibration data.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Essential methodology for building statistically sound evaluation pipelines with CI-reportable quality metrics and proper uncertainty estimates."
  },
  {
    "doi": "10.48550/arxiv.2510.08120",
    "title": "Interpreting LLM-as-a-Judge Policies via Verifiable Global Explanations",
    "authors": "Jasmina Gajcin, Erik Miehling, Rahul Nair",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "CLoVE and GloVE extract contrastive local and global policy explanations from LLM judges. Global policies are highly faithful to LLM-as-a-Judge decisions.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Extracting a global judge policy from the review agent's evaluation behavior makes severity assignments auditable and explainable to developers."
  },
  {
    "doi": "10.1101/2025.04.22.25326219",
    "title": "Automating Evaluation of AI Text Generation in Healthcare with LLM-as-a-Judge",
    "authors": "Emma Croxford, Yanjun Gao, Elliot First",
    "year": 2025,
    "venue": "medRxiv",
    "abstract_snippet": "GPT-o3-mini achieves ICC=0.818 with human evaluators using structured rubric. Reasoning models outperform non-reasoning models on rubric-based eval.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Confirms structured rubric-based LLM judges achieve near-human reliability; reasoning models preferred for rubric evaluation tasks like code review."
  },
  {
    "doi": "10.48550/arxiv.2510.09030",
    "title": "Automated Refinement of Essay Scoring Rubrics for Language Models via Reflect-and-Revise",
    "authors": "Keno Harada, Lui Yoshida, Takeshi Kojima",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Iteratively refines rubrics by reflecting on scoring rationales vs. human score discrepancies. Achieves QWK improvements up to 0.47 even from a simple initial rubric.",
    "category": "prompt_eval",
    "pr_agent_relevance": "The reflect-and-revise loop applies to PR review rubrics — agent self-improves criteria by comparing rationale against human-accepted/rejected review decisions."
  },
  {
    "doi": "10.48550/arxiv.2511.20836",
    "title": "Structured Prompting Enables More Robust, Holistic Evaluation of Language Models",
    "authors": "Asad Aali, Muhammad Ahmed Mohsin, Vasiliki Bikia",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "DSPy+HELM integration. Without structured prompting, HELM underestimates LM performance by 4%; CoT reduces sensitivity to prompt design.",
    "category": "prompt_eval",
    "pr_agent_relevance": "DSPy-style structured prompting for review evaluation improves benchmark stability and reduces variance in automated review quality measurements."
  },
  {
    "doi": "10.48550/arxiv.2510.01146",
    "title": "mR3: Multilingual Rubric-Agnostic Reward Reasoning Models",
    "authors": "David Anugraha, Shih-Lin Hung, Zilu Tang",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Rubric-agnostic reward model trained on 72 languages. Surpasses GPT-OSS-120B while 9× smaller. Rubrics provided per-task rather than baked into model.",
    "category": "prompt_eval",
    "pr_agent_relevance": "A rubric-agnostic reward model could evaluate different PR dimensions (security, correctness, style) with a single model by swapping rubric text."
  },
  {
    "doi": "10.48550/arxiv.2510.10539",
    "title": "Detecting Hallucinations in Authentic LLM-Human Interactions",
    "authors": "Yujie Ren, Niklas Gruhlke, Anne Lauscher",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "AuthenHallu benchmark from real LLM-human dialogues. 31.4% hallucination rate overall; 60% in Math/Number domains.",
    "category": "hallucination",
    "pr_agent_relevance": "Establishes ~30% baseline hallucination rate in real interactions; PR review agents should assume substantial verification overhead for factual code claims."
  },
  {
    "doi": "10.48550/arxiv.2511.11087",
    "title": "Can LLMs Detect Their Own Hallucinations?",
    "authors": "Sora Kadotani, Kosuke Nishida, Kyosuke Nishida",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Using CoT, GPT-3.5 Turbo detects 58.2% of its own hallucinations. LLMs with CoT can detect hallucinations if sufficient knowledge is in their parameters.",
    "category": "hallucination",
    "pr_agent_relevance": "Self-hallucination detection via CoT is feasible (~58% recall) but insufficient alone; external verification pass is still needed for code review claims."
  },
  {
    "doi": "10.48550/arxiv.2510.19507",
    "title": "Teaming LLMs to Detect and Mitigate Hallucinations",
    "authors": "Demian Till, John Smeaton, Peter Haubrick",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Multi-model consortium consistency substantially improves hallucination detection beyond single-model methods, often with reduced inference costs.",
    "category": "hallucination",
    "pr_agent_relevance": "Multi-model cross-validation of PR review security findings (Claude + Gemini) reduces false positives with cost savings vs. single-model sampling."
  },
  {
    "doi": "10.48550/arxiv.2511.12236",
    "title": "Consistency Is the Key: Detecting Hallucinations via Key Fact Inconsistencies",
    "authors": "Raavi Gupta, Pranav Hari Panicker, Sumit Bhatia",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "CONFACTCHECK: factual probes within generated text should be consistent within and across LLMs. Achieves higher accuracy with fewer API calls than baselines.",
    "category": "hallucination",
    "pr_agent_relevance": "Probing PR review factual claims with consistency queries provides a lightweight hallucination guard without requiring external knowledge bases."
  },
  {
    "doi": "10.48550/arxiv.2510.00296",
    "title": "Beyond Token Probes: Hallucination Detection via Activation Tensors with ACT-ViT",
    "authors": "Guy Bar-Shalom, Fabrizio Frasca, Yaniv Galron",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Vision Transformer on activation tensors across layers×tokens. Outperforms probing techniques, supports multi-LLM training, strong zero-shot performance.",
    "category": "hallucination",
    "pr_agent_relevance": "For white-box model access, activation-based hallucination detection could flag unreliable code review claims before they become posted comments."
  },
  {
    "doi": "10.48550/arxiv.2510.16549",
    "title": "ReviewGuard: Enhancing Deficient Peer Review Detection via LLM-Driven Data Augmentation",
    "authors": "Haoxuan Zhang, Ruochi Li, Sarthak Shrestha",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Detects deficient reviews. Deficient reviews show lower structural complexity and higher self-reported confidence. LLM augmentation improves recall from 0.55 to 0.67.",
    "category": "hallucination",
    "pr_agent_relevance": "Directly applicable: detect when the review agent produces a deficient PR review and trigger a re-review pass with higher evidence requirements."
  },
  {
    "doi": "10.48550/arxiv.2510.04040",
    "title": "FaithCoT-Bench: Benchmarking Instance-Level Faithfulness of Chain-of-Thought Reasoning",
    "authors": "Xu Shen, Song Wang, Zhen Tan",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "First benchmark for instance-level CoT unfaithfulness detection. 300+ unfaithful instances. Harder models produce more deceptively plausible but unfaithful CoT.",
    "category": "prompt_eval",
    "pr_agent_relevance": "CoT reasoning in PR review may be unfaithful; this benchmark provides detection methods (counterfactual, logit-based, LLM-as-judge) applicable to review trace auditing."
  },
  {
    "doi": "10.48550/arxiv.2510.07743",
    "title": "OpenRubrics: Towards Scalable Synthetic Rubric Generation for Reward Modeling and LLM Alignment",
    "authors": "Tianci Liu, Ran Xu, Tony Yu",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Contrastive Rubric Generation (CRG) derives hard rules and principles by contrasting preferred vs. rejected responses. Rubric-RM surpasses size-matched baselines by 6.8% on RewardBench.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Generating rubrics by contrasting accepted vs. rejected PR review comments produces discriminative PR-specific reward signals without manual rubric writing."
  },
  {
    "doi": "10.48550/arxiv.2510.00263",
    "title": "Judging with Confidence: Calibrating Autoraters to Preference Distributions",
    "authors": "Zhuohang Li, Xiaowei Li, Chengyu Huang",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "Framework for calibrating probabilistic autoraters to target preference distributions. Improved calibration and significantly lower positional bias.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Calibrating review agent severity judgments to developer acceptance distributions reduces systematic over-/under-severity bias in deployed agents."
  },
  {
    "doi": "10.48550/arxiv.2511.12464",
    "title": "Probing Preference Representations: Multi-Dimensional Evaluation and Analysis Method for Reward Models",
    "authors": "Chenglong Wang, Yifu Huo, Yang Gan",
    "year": 2025,
    "venue": "arXiv",
    "abstract_snippet": "MRMBench: six probing tasks for different preference dimensions. Reward models often struggle with multiple dimensions simultaneously. Inference-time probing provides confidence metric.",
    "category": "prompt_eval",
    "pr_agent_relevance": "Multi-dimensional reward model separately evaluating security/correctness/style would provide more granular PR review quality signals."
  }
]
```
