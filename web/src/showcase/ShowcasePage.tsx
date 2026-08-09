import { useState, type CSSProperties } from "react";
import { Link } from "react-router";

import { BrandLogo } from "../app/BrandLogo";

type DemoId = "product" | "ai" | "practice";
type SubtitleLanguage = "zh" | "en";

interface EvidenceLink {
  label: string;
  note: string;
  url: string;
}

interface DemoScene {
  id: DemoId;
  index: string;
  audience: string;
  title: string;
  question: string;
  sourceTitle: string;
  sourceCreator: string;
  sourceUrl: string;
  thumbnailUrl: string;
  subtitlePreview: Record<SubtitleLanguage, string>;
  subtitleDurationSeconds: Record<SubtitleLanguage, number>;
  answerLead: string;
  answerPoints: string[];
  evidence: EvidenceLink[];
}

const demoScenes: DemoScene[] = [
  {
    id: "product",
    index: "01",
    audience: "产品调研",
    title: "从礼貌反馈里，找出真实需求",
    question: "我该怎样采访早期用户，才不会只得到礼貌性的肯定？",
    sourceTitle: "How to Talk to Users",
    sourceCreator: "Eric Migicovsky · Y Combinator",
    sourceUrl: "https://www.youtube.com/watch?v=MT4Ig2uqjTc",
    thumbnailUrl: "https://i.ytimg.com/vi/MT4Ig2uqjTc/hqdefault.jpg",
    subtitlePreview: {
      zh: "每个人在早期客户访谈中都可以问的第一个问题是：你想解决的这件事，最困难的部分是什么？以 Dropbox 为例。很多人可能已经不记得没有 Dropbox 的世界了，但让我们回到 2005 年，想象创始人 Drew 在 MIT 读书时刚开始构思 Dropbox。你坐在 MIT 的计算机实验室里，旁边是你的朋友。你正在尝试理解人们如何分享文件，以及他们是不是潜在用户、有哪些问题可以用新技术解决。于是你转身问他：使用学校电脑完成小组项目时，最困难的部分是什么？你们正坐在计算机实验室里，这正是提出这种问题的自然场景。接下来用开放式对话了解对方目前如何与朋友协作完成小组项目。你希望听到具体痛点，例如登录共享电脑后，必须从某个地方取回文件，或依赖网络存储……",
      en: "Questions that everyone can ask during their early customer interviews: the first question is, what is the hardest part about doing the thing that you're trying to solve? Let's take Dropbox for an example. Put yourself back in the position of Drew, the founder of Dropbox, in 2005 when he was initially working on the idea while studying at MIT. Imagine you're in the computer lab and sitting next to your friend. You want to learn how other people are sharing files, whether they are potential users, and what problems you can help solve with this new technology. So you ask: what is the hardest part about working on a group project with school computers? It's the perfect context for an open-ended conversation about how that person currently works on group projects and the specific pain points they have.",
    },
    subtitleDurationSeconds: { zh: 112, en: 148 },
    answerLead: "不要先推销方案，也不要让用户预测未来。把对话拉回到已经发生过的具体经历。",
    answerPoints: [
      "先问最近一次遇到问题的时间、地点和上下文，而不是“你会不会用这个功能”。",
      "观察对方是否已经花时间或金钱寻找替代方案，用行动判断痛点强度。",
      "追问现有方案哪里不好，从具体缺口中提炼功能和产品表达。",
    ],
    evidence: [
      {
        label: "06:07",
        note: "从最难的具体环节开始提问",
        url: "https://www.youtube.com/watch?v=MT4Ig2uqjTc&t=367s",
      },
      {
        label: "08:16",
        note: "追问最近一次真实经历",
        url: "https://www.youtube.com/watch?v=MT4Ig2uqjTc&t=496s",
      },
      {
        label: "11:17",
        note: "检查用户是否主动找过解决办法",
        url: "https://www.youtube.com/watch?v=MT4Ig2uqjTc&t=677s",
      },
    ],
  },
  {
    id: "ai",
    index: "02",
    audience: "AI 入门",
    title: "把抽象概念，拆成能复述的结构",
    question: "用高中生能理解的方式解释：神经网络到底在做什么？",
    sourceTitle: "But what is a neural network?",
    sourceCreator: "Grant Sanderson · 3Blue1Brown",
    sourceUrl: "https://www.youtube.com/watch?v=aircAruvnKk",
    thumbnailUrl: "https://i.ytimg.com/vi/aircAruvnKk/hqdefault.jpg",
    subtitlePreview: {
      zh: "现在，当我说“神经元”时，你只需要把它想成一个保存数字的东西，具体来说，是 0 到 1 之间的数字，并没有更复杂。网络从一组与输入图像 28×28 个像素一一对应的神经元开始，总共 784 个。每个神经元保存一个代表对应像素灰度值的数字：黑色像素是 0，白色像素是 1。神经元里的这个数字叫作激活值。你可以想象，激活值越高，神经元就亮得越明显。这 784 个神经元组成网络的第一层。再跳到最后一层，这里有 10 个神经元，分别代表 10 个数字。每个神经元的激活值仍然介于 0 和 1 之间，表示系统认为输入图像属于某个数字的程度。中间还有几层隐藏层；暂时可以把它们视为一个巨大的问号：识别数字的过程究竟是如何完成的？",
      en: "Right now when I say neuron, all I want you to think about is a thing that holds a number, specifically a number between 0 and 1. The network starts with neurons corresponding to each of the 28×28 pixels of the input image, which is 784 neurons in total. Each one holds a number representing the grayscale value of the corresponding pixel, ranging from 0 for black pixels up to 1 for white pixels. This number is called its activation. These 784 neurons make up the first layer. The last layer has 10 neurons, each representing one of the digits. Their activations represent how much the system thinks that a given image corresponds with a given digit. There are also a couple of hidden layers in between, which for now can remain a giant question mark.",
    },
    subtitleDurationSeconds: { zh: 108, en: 136 },
    answerLead: "可以先把它理解成一个会调参数的数字转换器：输入很多数字，经过多层变换，输出一组判断结果。",
    answerPoints: [
      "示例把一张 28×28 的手写数字图片转换成 784 个亮度值，每个值进入一个输入神经元。",
      "中间层根据权重和偏置计算新的激活值，让像素逐层组合成边缘、形状等更高层特征。",
      "整个网络本质上是一个从 784 个输入到 10 个输出的函数；训练就是不断调整其中的参数。",
    ],
    evidence: [
      {
        label: "03:08",
        note: "28×28 像素如何成为 784 个输入",
        url: "https://www.youtube.com/watch?v=aircAruvnKk&t=188s",
      },
      {
        label: "04:03",
        note: "隐藏层与逐层激活",
        url: "https://www.youtube.com/watch?v=aircAruvnKk&t=243s",
      },
      {
        label: "15:39",
        note: "把整个网络理解成一个函数",
        url: "https://www.youtube.com/watch?v=aircAruvnKk&t=939s",
      },
    ],
  },
  {
    id: "practice",
    index: "03",
    audience: "技能训练",
    title: "把“多练”变成“有效地练”",
    question: "怎样让技能练习更有效，而不是机械重复？",
    sourceTitle: "How to practice effectively...for just about anything",
    sourceCreator: "Annie Bosler & Don Greene · TED-Ed",
    sourceUrl: "https://www.youtube.com/watch?v=f2O6mQkFiiw",
    thumbnailUrl: "https://i.ytimg.com/vi/f2O6mQkFiiw/hqdefault.jpg",
    subtitlePreview: {
      zh: "掌握一项技能需要多久？我们还没有一个神奇的固定数字，但已经知道，精通并不只取决于练习了多少小时，还取决于练习的质量和有效性。有效练习应当持续、极度专注，并针对接近当前能力边缘的内容或弱项。如果有效练习是关键，怎样才能最大化利用练习时间？可以尝试这些方法：专注眼前任务，关闭电脑或电视，把手机调到飞行模式，尽量减少干扰。一项针对 260 名学生的研究发现，他们平均只能连续专注六分钟；笔记本电脑、智能手机，尤其是 Facebook，是主要干扰来源。开始时放慢速度，甚至使用慢动作。协调能力会被每一次重复塑造，无论动作正确还是错误。先保持高质量重复，再逐渐提速，更可能把动作做对。接下来，频繁重复并安排休息，也是顶尖练习者常见的习惯。研究显示，许多顶尖运动员、音乐家和舞者每周会花 50 到 60 小时从事与专业相关的活动。",
      en: "While we don't yet have a magic number for mastering a skill, we know that mastery isn't simply about the amount of hours of practice. It's also the quality and effectiveness of that practice. Effective practice is consistent, intensely focused, and targets weaknesses at the edge of one's current abilities. So how can we get the most out of practice time? Focus on the task at hand and minimize distractions by turning off the computer or TV and putting your phone on airplane mode. In one study, 260 students stayed on task for only six minutes at a time; laptops, smartphones, and Facebook were the main distractions. Start slowly or in slow motion. Coordination is built with repetitions, correct or incorrect. Gradually increasing the speed of quality repetitions gives you a better chance of doing them correctly. Frequent repetitions with allotted breaks are also common habits of elite performers.",
    },
    subtitleDurationSeconds: { zh: 118, en: 142 },
    answerLead: "有效练习不只看时长，更看注意力、难度边界和反馈质量。",
    answerPoints: [
      "练习时减少干扰，把注意力集中在当前任务和最薄弱的环节上。",
      "新动作先放慢，优先建立正确且高质量的重复，再逐渐提高速度。",
      "把练习拆成多次短时段并安排休息；动作已经建立后，也可以用清晰的心理演练巩固。",
    ],
    evidence: [
      {
        label: "02:26",
        note: "持续、专注且贴近能力边界",
        url: "https://www.youtube.com/watch?v=f2O6mQkFiiw&t=146s",
      },
      {
        label: "03:05",
        note: "先慢速练出正确动作",
        url: "https://www.youtube.com/watch?v=f2O6mQkFiiw&t=185s",
      },
      {
        label: "03:18",
        note: "高频重复与间隔休息",
        url: "https://www.youtube.com/watch?v=f2O6mQkFiiw&t=198s",
      },
    ],
  },
];

type AudienceIconName = "learner" | "research" | "creator" | "channels";

const audienceIconPaths: Record<AudienceIconName, string[]> = {
  learner: [
    "M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0",
    "M6 21v-2a4 4 0 0 1 4 -4h.5",
    "M17.8 20.817l-2.172 1.138a.392 .392 0 0 1 -.568 -.41l.415 -2.411l-1.757 -1.707a.389 .389 0 0 1 .217 -.665l2.428 -.352l1.086 -2.193a.392 .392 0 0 1 .702 0l1.086 2.193l2.428 .352a.39 .39 0 0 1 .217 .665l-1.757 1.707l.414 2.41a.39 .39 0 0 1 -.567 .411l-2.172 -1.138",
  ],
  research: [
    "M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0",
    "M6 21v-2a4 4 0 0 1 4 -4h1.5",
    "M15 18a3 3 0 1 0 6 0a3 3 0 1 0 -6 0",
    "M20.2 20.2l1.8 1.8",
  ],
  creator: [
    "M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0",
    "M6 21v-2a4 4 0 0 1 4 -4h3.5",
    "M18.42 15.61a2.1 2.1 0 0 1 2.97 2.97l-3.39 3.42h-3v-3l3.42 -3.39",
  ],
  channels: [
    "M10 13a2 2 0 1 0 4 0a2 2 0 0 0 -4 0",
    "M8 21v-1a2 2 0 0 1 2 -2h4a2 2 0 0 1 2 2v1",
    "M15 5a2 2 0 1 0 4 0a2 2 0 0 0 -4 0",
    "M17 10h2a2 2 0 0 1 2 2v1",
    "M5 5a2 2 0 1 0 4 0a2 2 0 0 0 -4 0",
    "M3 13v-1a2 2 0 0 1 2 -2h2",
  ],
};

function AudienceIcon({ name }: { name: AudienceIconName }) {
  return (
    <span className="showcase-audience__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {audienceIconPaths[name].map((path) => <path key={path} d={path} />)}
      </svg>
    </span>
  );
}

const audiences: Array<{ icon: AudienceIconName; title: string; copy: string }> = [
  {
    icon: "learner",
    title: "深度学习者",
    copy: "收藏了大量课程、访谈和演讲，希望按问题重新调取，而不是从头重看。",
  },
  {
    icon: "research",
    title: "研究与产品团队",
    copy: "需要跨视频比对观点，并把每个结论快速定位回原始上下文。",
  },
  {
    icon: "creator",
    title: "创作者与知识工作者",
    copy: "想把看过的内容变成可复用素材，同时保留标题、片段与时间戳。",
  },
  {
    icon: "channels",
    title: "多渠道使用者",
    copy: "如果部署启用了多个聊天入口，绑定后的账号可以共用一份私人资料库，并通过已启用的可信入口完成 Web 登录。",
  },
];

const processSteps = [
  {
    index: "01",
    title: "提交并归档视频来源",
    copy: "通过已启用的聊天入口或 Web 资料库保存 YouTube 链接，并补充保存理由或预期用途，便于后续识别与筛选。",
    output: "视频来源 + 保存说明",
  },
  {
    index: "02",
    title: "异步解析并建立索引",
    copy: "系统在后台提取视频标题、章节与字幕，将长内容切分为可检索片段，并保留片段与原视频之间的对应关系。",
    output: "字幕与章节 → 内容索引",
  },
  {
    index: "03",
    title: "在个人资料库中检索",
    copy: "用户可以直接用自然语言描述问题；系统只在当前账户的资料库范围内定位相关片段，并组织回答所需的上下文。",
    output: "自然语言问题 → 相关原文",
  },
  {
    index: "04",
    title: "生成带来源依据的回答",
    copy: "回答基于检索到的原文片段生成，并附带视频标题、引用摘录和可跳转时间点，方便回到完整语境核对。",
    output: "回答依据 + 原视频时间点",
  },
];

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

const typingSentencePause = 6;
const typingCharacterDurationMs = 12;

function TypewriterText({ text, startIndex }: { text: string; startIndex: number }) {
  return (
    <>
      <span className="sr-only">{text}</span>
      <span className="demo-typewriter" aria-hidden="true">
        {Array.from(text).map((character, index) => (
          <span
            className="demo-typewriter__char"
            key={`${index}-${character}`}
            style={{ "--typing-index": startIndex + index } as CSSProperties}
          >
            {character}
          </span>
        ))}
      </span>
    </>
  );
}

export function ShowcasePage() {
  const [activeDemoId, setActiveDemoId] = useState<DemoId>("product");
  const [heroCoverId, setHeroCoverId] = useState<DemoId | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [subtitleLanguage, setSubtitleLanguage] = useState<SubtitleLanguage>("zh");
  const activeDemo = demoScenes.find((scene) => scene.id === activeDemoId) ?? demoScenes[0];
  const activeSubtitle = activeDemo.subtitlePreview[subtitleLanguage];
  const subtitleStyle = {
    "--demo-subtitle-duration": `${activeDemo.subtitleDurationSeconds[subtitleLanguage]}s`,
  } as CSSProperties;
  const answerSegments = [activeDemo.answerLead, ...activeDemo.answerPoints];
  const answerOffsets = answerSegments.map((_, segmentIndex) => (
    answerSegments
      .slice(0, segmentIndex)
      .reduce((total, segment) => total + Array.from(segment).length + typingSentencePause, 0)
  ));
  const answerTypingCharacterCount = answerSegments.reduce(
    (total, segment) => total + Array.from(segment).length + typingSentencePause,
    0,
  );
  const answerStyle = {
    "--answer-typing-end": `${answerTypingCharacterCount * typingCharacterDurationMs + 180}ms`,
  } as CSSProperties;

  function selectDemo(id: DemoId) {
    setActiveDemoId(id);
    setHasRun(false);
  }

  return (
    <div className="showcase-page">
      <a className="showcase-skip" href="#showcase-main">跳到主要内容</a>

      <header className="showcase-nav">
        <Link className="showcase-brand" to="/" aria-label="Notebook Agent 首页">
          <BrandLogo className="showcase-brand__mark" />
          <span>NOTEBOOK / AGENT</span>
        </Link>
        <nav aria-label="展示页导航">
          <a href="#purpose">项目目的</a>
          <a href="#process">使用流程</a>
          <a href="#demo">试用场景</a>
        </nav>
        <Link className="showcase-nav__cta" to="/login">进入资料库 <ArrowIcon /></Link>
      </header>

      <main id="showcase-main" tabIndex={-1}>
        <section className="showcase-hero" aria-labelledby="showcase-title">
          <div className="showcase-hero__grid" aria-hidden="true" />
          <div className="showcase-hero__copy">
            <p className="showcase-kicker"><span>你的私人视频资料库</span><span>2026 / HACKATHON</span></p>
            <h1 id="showcase-title">让收藏过的知识，<em>再次可用。</em></h1>
            <p className="showcase-hero__lead">
              散落在视频中的知识与信息，从此成为你的助手与知识库。
            </p>
            <div className="showcase-hero__actions">
              <a className="showcase-button showcase-button--signal" href="#demo">先试一个真实场景 <ArrowIcon /></a>
              <a className="showcase-button showcase-button--line" href="#process">查看工作方式</a>
            </div>
          </div>

          <div className="showcase-hero__instrument" aria-label="从视频到可追溯答案的处理路径">
            <div
              className="instrument-cover-stack"
              aria-label="资料库中的三个真实视频来源"
              onMouseLeave={() => setHeroCoverId(null)}
            >
              {demoScenes.map((scene, index) => (
                <a
                  className={`instrument-cover${heroCoverId === scene.id ? " is-front" : ""}`}
                  href="#demo"
                  aria-label={`打开 ${scene.sourceTitle} 问答场景`}
                  key={scene.id}
                  onMouseEnter={() => setHeroCoverId(scene.id)}
                  onFocus={() => setHeroCoverId(scene.id)}
                  onBlur={() => setHeroCoverId(null)}
                  onClick={() => selectDemo(scene.id)}
                >
                  <span className="instrument-cover__wire" aria-hidden="true" />
                  <img
                    src={scene.thumbnailUrl}
                    alt={`${scene.sourceTitle} 视频封面`}
                    width="480"
                    height="360"
                    decoding="async"
                    fetchPriority={index === demoScenes.length - 1 ? "high" : "auto"}
                  />
                  <span className="instrument-cover__caption">
                    <span>{scene.index}</span>
                    <strong>{scene.sourceTitle}</strong>
                  </span>
                </a>
              ))}
            </div>
            <div className="instrument-readout">
              <p><span>你收藏</span><strong>一段 YouTube 视频</strong></p>
              <p><span>系统整理</span><strong>字幕与重点内容</strong></p>
              <p><span>你获得</span><strong>答案 / 原文 / 时间点</strong></p>
            </div>
          </div>

          <div className="showcase-hero__rail" aria-label="项目核心能力">
            <span>01 / 收藏</span>
            <span>02 / 理解</span>
            <span>03 / 检索</span>
            <span>04 / 回源</span>
          </div>
        </section>

        <section className="showcase-section showcase-purpose" id="purpose" aria-labelledby="purpose-title">
          <div className="showcase-section__label">
            <span>01</span>
            <p>WHY IT EXISTS</p>
          </div>
          <div className="showcase-purpose__content">
            <p className="showcase-overline">项目目的</p>
              <h2 id="purpose-title">不要让遗忘成为<br /><em>收藏视频的终点。</em></h2>
            <div className="showcase-purpose__statement">
              <p>
                当我们按下收藏键的刹那，你是否会想到这是你最后一次与你的视频碰面？我们不希望视频只成为收藏夹的一串链接，我们希望当你有需要的时候，能一眼找到你想要的内容。Notebook Agent 不仅能帮你记住视频在哪里，更能提醒你视频讲了什么。
              </p>
              <p>
                它先从你的资料库里找到相关原文，再组织答案；找不到时会明确说明，不会凭模型记忆补出一个看似合理的结论。
              </p>
            </div>
          </div>
          <div className="showcase-purpose__proofs" aria-label="项目原则">
            <article>
              <span>01</span>
              <h3>独立资料空间</h3>
              <p>每位用户拥有独立的私人资料库。页面内容、检索结果与回答依据都限定在当前账户范围内，不与其他用户的数据混用。</p>
            </article>
            <article>
              <span>02</span>
              <h3>基于原文生成回答</h3>
              <p>系统先检索资料库中的相关字幕片段，再据此组织答案；缺少足够依据时会明确说明，不用模型记忆补全。</p>
            </article>
            <article>
              <span>03</span>
              <h3>答案依据全程可追溯</h3>
              <p>回答会同时关联视频标题、原文片段与对应时间点，方便随时返回原视频，核对结论所在的完整上下文。</p>
            </article>
          </div>
        </section>

        <section className="showcase-section showcase-audience" aria-labelledby="audience-title">
          <div className="showcase-section__label">
            <span>02</span>
            <p>WHO IT SERVES</p>
          </div>
          <div className="showcase-audience__heading">
            <p className="showcase-overline">适用人群</p>
            <h2 id="audience-title">
              <span className="showcase-audience__lead-in">为了让你跳过等待而设计：</span>
              <span>“我好像看过这个……<br />我找找？”</span>
            </h2>
          </div>
          <div className="showcase-audience__grid">
            {audiences.map((audience) => (
              <article key={audience.title}>
                <AudienceIcon name={audience.icon} />
                <h3>{audience.title}</h3>
                <p>{audience.copy}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="showcase-section showcase-process" id="process" aria-labelledby="process-title">
          <div className="showcase-section__label showcase-section__label--light">
            <span>03</span>
            <p>HOW IT WORKS</p>
          </div>
          <div className="showcase-process__heading">
            <p className="showcase-overline">视频知识处理流程</p>
            <h2 id="process-title">从视频归档，<br />到可追溯的回答。</h2>
            <p>视频链接提交后，系统会在后台提取标题、章节和字幕，建立可检索的内容索引；处理期间不影响继续聊天或浏览资料库。</p>
          </div>
          <ol className="showcase-process__list">
            {processSteps.map((step) => (
              <li key={step.index}>
                <span className="process-index">{step.index}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.copy}</p>
                </div>
                <code>{step.output}</code>
              </li>
            ))}
          </ol>
        </section>

        <section className="showcase-section showcase-demo" id="demo" aria-labelledby="demo-title">
          <div className="showcase-section__label">
            <span>04</span>
            <p>TRY THE FLOW</p>
          </div>
          <div className="showcase-demo__heading">
            <div>
              <p className="showcase-overline">真实来源 · 预设试用</p>
              <h2 id="demo-title">选一个场景，<br />看答案出处。</h2>
            </div>
            <p>
              下列答案是根据公开字幕预先整理的交互演示，不会调用模型或上传数据。真实使用时，来源会替换成你自己的资料库内容。
            </p>
          </div>

          <div className="demo-selector" aria-label="选择试用场景">
            {demoScenes.map((scene) => (
              <button
                className={scene.id === activeDemoId ? "is-active" : undefined}
                key={scene.id}
                type="button"
                aria-pressed={scene.id === activeDemoId}
                onClick={() => selectDemo(scene.id)}
              >
                <span>{scene.index}</span>
                <strong>{scene.audience}</strong>
                <small>{scene.title}</small>
              </button>
            ))}
          </div>

          <div className="demo-workbench">
            <aside className="demo-source-card">
              <div className="demo-source-card__visual">
                <img
                  src={activeDemo.thumbnailUrl}
                  alt={`当前场景：${activeDemo.sourceTitle} 视频封面`}
                  width="480"
                  height="360"
                  decoding="async"
                />
                <div className="demo-subtitle-language" role="group" aria-label="字幕语言">
                  <button
                    type="button"
                    aria-label="显示中文字幕"
                    aria-pressed={subtitleLanguage === "zh"}
                    onClick={() => setSubtitleLanguage("zh")}
                  >中</button>
                  <button
                    type="button"
                    aria-label="显示英文字幕"
                    aria-pressed={subtitleLanguage === "en"}
                    onClick={() => setSubtitleLanguage("en")}
                  >EN</button>
                </div>
                <div className="demo-subtitle-bar" data-testid="demo-subtitle-ticker">
                  <span className="demo-subtitle-bar__mark" aria-hidden="true">CC</span>
                  <div className="demo-subtitle-viewport" aria-hidden="true">
                    <div
                      className="demo-subtitle-track"
                      key={`${activeDemo.id}-${subtitleLanguage}`}
                      style={subtitleStyle}
                    >
                      <span>{activeSubtitle}</span>
                      <span>{activeSubtitle}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="demo-source-card__body">
                <p className="showcase-overline">已导入来源</p>
                <h3>{activeDemo.sourceTitle}</h3>
                <p>{activeDemo.sourceCreator}</p>
                <div className="demo-source-card__status">
                  <span><i /> 字幕已整理</span>
                  <span>内容已可查找</span>
                </div>
                <a href={activeDemo.sourceUrl} target="_blank" rel="noreferrer">
                  查看原视频 <ArrowIcon />
                </a>
              </div>
            </aside>

            <div className="demo-console">
              <div className="demo-console__bar">
                <span>NOTEBOOK AGENT / 场景试用</span>
                <span className="demo-console__mode"><i /> 来源核对模式</span>
              </div>
              <div className="demo-question">
                <span>你的问题</span>
                <p>{activeDemo.question}</p>
              </div>
              <div className="demo-pipeline" aria-label="回答生成步骤">
                <span className={hasRun ? "is-complete" : undefined}>01 理解问题</span>
                <span className={hasRun ? "is-complete" : undefined}>02 查找相关片段</span>
                <span className={hasRun ? "is-complete" : undefined}>03 核对原文</span>
              </div>
              {!hasRun ? (
                <div className="demo-console__ready">
                  <button className="showcase-button showcase-button--signal" type="button" onClick={() => setHasRun(true)}>
                    查看这次回答 <ArrowIcon />
                  </button>
                </div>
              ) : (
                <article className="demo-answer" aria-live="polite" style={answerStyle}>
                  <div className="demo-answer__label"><BrandLogo className="demo-answer__mark" /><p>基于 3 个字幕片段</p></div>
                  <p className="demo-answer__lead">
                    <TypewriterText text={activeDemo.answerLead} startIndex={answerOffsets[0]} />
                  </p>
                  <ol>
                    {activeDemo.answerPoints.map((point, index) => (
                      <li key={point}>
                        <TypewriterText text={point} startIndex={answerOffsets[index + 1]} />
                      </li>
                    ))}
                  </ol>
                  <div className="demo-evidence">
                    <p>可核对证据</p>
                    {activeDemo.evidence.map((evidence) => (
                      <a href={evidence.url} key={evidence.url} target="_blank" rel="noreferrer">
                        <strong>{evidence.label}</strong>
                        <span>{evidence.note}</span>
                        <ArrowIcon />
                      </a>
                    ))}
                  </div>
                  <button className="demo-reset" type="button" onClick={() => setHasRun(false)}>收起答案</button>
                </article>
              )}
            </div>
          </div>
        </section>

        <section className="showcase-cta" aria-labelledby="showcase-cta-title">
          <p className="showcase-overline">YOUR KNOWLEDGE / YOUR EVIDENCE</p>
          <h2 id="showcase-cta-title">下次需要答案，<br />直接回到原文。</h2>
          <Link className="showcase-button showcase-button--dark" to="/login">进入私人资料库 <ArrowIcon /></Link>
          <p className="showcase-cta__note">本页展示已经实现的 YouTube 资料库流程 · 可用登录入口以当前部署配置为准</p>
        </section>
      </main>

      <footer className="showcase-footer">
        <Link className="showcase-brand showcase-brand--footer" to="/">
          <BrandLogo className="showcase-brand__mark" />
          <span>NOTEBOOK / AGENT</span>
        </Link>
        <p>Built for EAZO Global Hackathon</p>
        <a href="#showcase-main">回到顶部 ↑</a>
      </footer>
    </div>
  );
}
