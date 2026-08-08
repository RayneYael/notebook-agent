import { useState } from "react";
import { Link } from "react-router";

type DemoId = "product" | "ai" | "practice";

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

const audiences = [
  {
    index: "A",
    title: "深度学习者",
    copy: "收藏了大量课程、访谈和演讲，希望按问题重新调取，而不是从头重看。",
  },
  {
    index: "B",
    title: "研究与产品团队",
    copy: "需要跨视频比对观点，并把每个结论快速定位回原始上下文。",
  },
  {
    index: "C",
    title: "创作者与知识工作者",
    copy: "想把看过的内容变成可复用素材，同时保留标题、片段与时间戳。",
  },
  {
    index: "D",
    title: "多渠道使用者",
    copy: "如果部署启用了多个聊天入口，绑定后的账号可以共用一份私人资料库，并通过已启用的可信入口完成 Web 登录。",
  },
];

const processSteps = [
  {
    index: "01",
    title: "投递一个链接",
    copy: "在已启用的聊天入口或 Web 资料库中保存 YouTube 视频，并写下保存说明。",
    output: "视频链接 + 保存说明",
  },
  {
    index: "02",
    title: "异步知识化",
    copy: "系统在后台读取视频信息和字幕，把长内容整理成可查找的重点片段。",
    output: "字幕 → 可查找的内容",
  },
  {
    index: "03",
    title: "用自然语言提问",
    copy: "系统只在你的资料库里查找，同时按关键词和问题表达的意思找到相关原文。",
    output: "问题 → 相关原文",
  },
  {
    index: "04",
    title: "核对并回到原文",
    copy: "回答只使用刚找到的原文片段，并附带标题、摘录和可跳转时间点。",
    output: "答案 + 原视频时间点",
  },
];

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

export function ShowcasePage() {
  const [activeDemoId, setActiveDemoId] = useState<DemoId>("product");
  const [hasRun, setHasRun] = useState(false);
  const activeDemo = demoScenes.find((scene) => scene.id === activeDemoId) ?? demoScenes[0];

  function selectDemo(id: DemoId) {
    setActiveDemoId(id);
    setHasRun(false);
  }

  return (
    <div className="showcase-page">
      <a className="showcase-skip" href="#showcase-main">跳到主要内容</a>

      <header className="showcase-nav">
        <Link className="showcase-brand" to="/" aria-label="Notebook Agent 首页">
          <span className="showcase-brand__mark" aria-hidden="true">N</span>
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
              Notebook Agent 把散落在视频里的观点，转化成一份能提问、能检索、能回到原文的私人记忆。
            </p>
            <div className="showcase-hero__actions">
              <a className="showcase-button showcase-button--signal" href="#demo">先试一个真实场景 <ArrowIcon /></a>
              <a className="showcase-button showcase-button--line" href="#process">查看工作方式</a>
            </div>
          </div>

          <div className="showcase-hero__instrument" aria-label="从视频到可追溯答案的处理路径">
            <div className="instrument-orbit" aria-hidden="true">
              <span className="instrument-orbit__core">N</span>
              <span className="instrument-orbit__dot instrument-orbit__dot--one" />
              <span className="instrument-orbit__dot instrument-orbit__dot--two" />
            </div>
            <div className="instrument-readout">
              <p><span>你收藏</span><strong>一段 YouTube 视频</strong></p>
              <p><span>系统整理</span><strong>字幕与重点内容</strong></p>
              <p><span>你获得</span><strong>答案 / 原文 / 时间点</strong></p>
            </div>
            <span className="instrument-status"><i /> 来源可核对</span>
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
            <h2 id="purpose-title">收藏不是终点。<br />真正的问题是：<em>需要时还能不能找到。</em></h2>
            <div className="showcase-purpose__statement">
              <p>
                我们会保存很多视频，却很少有时间重新看完。传统收藏夹只记得“链接在哪里”，Notebook Agent 更进一步，记住“视频里讲了什么”。
              </p>
              <p>
                它先从你的资料库里找到相关原文，再组织答案；找不到时会明确说明，不会凭模型记忆补出一个看似合理的结论。
              </p>
            </div>
          </div>
          <div className="showcase-purpose__proofs" aria-label="项目原则">
            <article>
              <span>01</span>
              <h3>每个人一份资料库</h3>
              <p>每位用户只能查看自己的资料库，页面与回答都不会混入其他人的内容。</p>
            </article>
            <article>
              <span>02</span>
              <h3>先找原文，再回答</h3>
              <p>回答只能引用服务端允许的真实片段，拒绝伪造来源。</p>
            </article>
            <article>
              <span>03</span>
              <h3>每个结论都能回看</h3>
              <p>标题、原文片段与视频时间戳一起返回，结论随时可核对。</p>
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
            <h2 id="audience-title">适合不想让“看过”<br />等于“忘过”的人。</h2>
          </div>
          <div className="showcase-audience__grid">
            {audiences.map((audience) => (
              <article key={audience.index}>
                <span>{audience.index}</span>
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
            <p className="showcase-overline">分步骤使用流程</p>
            <h2 id="process-title">从一个链接，到一条有出处的答案。</h2>
            <p>真实产品中的导入在后台异步完成，不会阻塞聊天或浏览。</p>
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
              <h2 id="demo-title">选择一个场景，看看证据怎样变成答案。</h2>
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
              <div className="demo-source-card__visual" aria-hidden="true">
                <span>{activeDemo.index}</span>
                <i />
                <b>字幕</b>
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
                  <p>这组公开视频与时间点已经提前核对。点击下方按钮，查看系统如何从原文整理出答案。</p>
                  <button className="showcase-button showcase-button--signal" type="button" onClick={() => setHasRun(true)}>
                    查看这次回答 <ArrowIcon />
                  </button>
                </div>
              ) : (
                <article className="demo-answer" aria-live="polite">
                  <div className="demo-answer__label"><span>N</span><p>基于 3 个字幕片段</p></div>
                  <p className="demo-answer__lead">{activeDemo.answerLead}</p>
                  <ol>
                    {activeDemo.answerPoints.map((point) => <li key={point}>{point}</li>)}
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
          <h2 id="showcase-cta-title">下一次需要答案时，<br />不必从收藏夹重新开始。</h2>
          <Link className="showcase-button showcase-button--dark" to="/login">进入私人资料库 <ArrowIcon /></Link>
          <p className="showcase-cta__note">本页展示已经实现的 YouTube 资料库流程 · 可用登录入口以当前部署配置为准</p>
        </section>
      </main>

      <footer className="showcase-footer">
        <Link className="showcase-brand showcase-brand--footer" to="/">
          <span className="showcase-brand__mark" aria-hidden="true">N</span>
          <span>NOTEBOOK / AGENT</span>
        </Link>
        <p>Built for EAZO Global Hackathon</p>
        <a href="#showcase-main">回到顶部 ↑</a>
      </footer>
    </div>
  );
}
