// The renderer never sees provider credentials or opens network connections.
let projectId = null;
let transport;
let connectPromise;
export function connect() {
  if (connectPromise) return connectPromise;
  connectPromise = new Promise((resolve, reject) => {
    if (!window.qt?.webChannelTransport || !window.QWebChannel) {
      reject(
        new Error("请通过墨境桌面程序启动工作区。此页面不提供在线模型服务。"),
      );
      return;
    }
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
      transport = channel.objects.workspace;
      resolve(transport);
    });
  });
  return connectPromise;
}
export async function api(op, data = {}) {
  const bridge = await connect();
  return new Promise((resolve, reject) =>
    bridge.invoke(
      op,
      JSON.stringify({ ...data, _project: data._project ?? projectId }),
      (result) => {
        try {
          const r = JSON.parse(result);
          if (!r.ok) {
            reject(new Error(r.error));
            return;
          }
          if (op === "state") projectId = r.data.project?.id || null;
          resolve(r.data);
        } catch (error) {
          reject(error);
        }
      },
    ),
  );
}
export async function upload(file, target, asset) {
  if (file.size > 25 * 1024 * 1024) throw new Error("单文件限 25 MB");
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
  return api("upload", { name: file.name, data, target, asset });
}
