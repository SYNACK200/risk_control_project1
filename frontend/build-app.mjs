// 以 /app/ 子路径构建借款侧前端（避开 shell 路径转换）
import { build } from 'vite';

await build({ base: '/app/' });
