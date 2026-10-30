// 以 /bank/ 子路径构建银行侧前端（避免 shell 对 /bank/ 做路径转换）
import { build } from 'vite';

await build({ base: '/bank/' });
