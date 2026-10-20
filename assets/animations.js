// Local figure documents size themselves to their content at every viewport.
for (const frame of document.querySelectorAll('.ghb-animation iframe')) {
  const connect = () => {
    const main = frame.contentDocument?.querySelector('main');
    if (!main) return;
    const resize = () => {
      frame.style.height = `${Math.ceil(main.getBoundingClientRect().height)}px`;
    };
    resize();
    new ResizeObserver(resize).observe(main);
  };
  frame.addEventListener('load', connect);
  connect();
}
