import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { emotions, type Emotion } from '@mood/contracts';
import './styles.css';

function App() {
  const [selected, setSelected] = useState<Emotion | null>(null);
  const [history, setHistory] = useState<{ emotion: Emotion; time: string }[]>([]);
  const [message, setMessage] = useState('');
  const submit = () => {
    if (!selected) return;
    setHistory((current) => [
      {
        emotion: selected,
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      },
      ...current,
    ]);
    setMessage('已记录在当前页面的演示历史中。');
    setSelected(null);
  };
  return (
    <main>
      <a className="brand" href="#">
        ☀ 课堂心晴 <span>学生端框架</span>
      </a>
      <div className="demo">本地演示 · 尚未接入登录、课程与提交接口</div>
      <div className="course">
        软件工程实践 <span>演示课堂</span>
      </div>
      <h1>此刻，你的课堂心情是？</h1>
      <p>轻触一个表情，给课堂一份反馈。</p>
      <div className="emotions">
        {Object.entries(emotions).map(([key, value]) => (
          <button
            key={key}
            aria-pressed={selected === key}
            onClick={() => {
              setSelected(key as Emotion);
              setMessage('');
            }}
          >
            <span>{value.emoji}</span>
            {value.label}
          </button>
        ))}
      </div>
      <button className="submit" disabled={!selected} onClick={submit}>
        记录我的心情
      </button>
      <p role="status" className="status">
        {message}
      </p>
      <section>
        <h2>
          本次演示记录 <span>{history.length} 条</span>
        </h2>
        {history.length ? (
          <ul>
            {history.map((record, index) => (
              <li key={index}>
                <span>
                  {emotions[record.emotion].emoji} {emotions[record.emotion].label}
                </span>
                <time>{record.time}</time>
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">还没有反馈，选一个表情开始吧。</p>
        )}
      </section>
      <footer>学生端与管理端独立运行 · 共享情绪类型契约</footer>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
