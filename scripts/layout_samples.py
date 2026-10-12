"""Generate a local visual test gallery. No model calls or private chat data.

python scripts/layout_samples.py OUTPUT_DIR --endpoint http://nekro_html2img:3000
Omit --endpoint to generate HTML/SVG/JSON only.
"""
import argparse
import asyncio
import json
import struct
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
package = types.ModuleType('group_relations')
package.__path__ = [str(root)]
sys.modules['group_relations'] = package
from group_relations.render import graph_svg, image_html, overview
from layout_fixtures import CASES, make_report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--endpoint', default='')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cards = []
    for key, title, count, kind, role_count in CASES:
        report = make_report(count, kind, role_count)
        report['channel_name'] = title+' · 模拟数据'
        svg, page = graph_svg(report), image_html(report)
        (args.output/f'{key}.svg').write_text(svg, encoding='utf-8')
        (args.output/f'{key}.html').write_text(page, encoding='utf-8')
        (args.output/f'{key}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        extension = 'svg'
        dimensions = ''
        if args.endpoint:
            import httpx
            async with httpx.AsyncClient(timeout=90) as client:
                result = await client.post(args.endpoint.rstrip('/')+'/screenshot', json={
                    'html':page, 'options':{'type':'png','fullPage':True},
                    'viewport':{'width':1480,'height':800,'deviceScaleFactor':1},
                    'waitForFunction':{'fn':"document.fonts.status === 'loaded' && Array.from(document.images).every(i => i.complete)"}})
                result.raise_for_status()
                if not result.content.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('Renderer did not return PNG')
                width, height = struct.unpack('>II', result.content[16:24])
                if width != 1480 or height >= 1480:
                    raise ValueError(f'{key}: report is not compact: {width}x{height}')
                (args.output/f'{key}.png').write_bytes(result.content)
                dimensions = f' · {width}×{height}'
                extension = 'png'
        shown = len(overview(report)['nodes'])
        cards.append(f'<section><h2>{title}</h2><p>{count}人 / 概览{shown}人 / {role_count}条关系{dimensions}</p>'
                     f'<a href="{key}.{extension}"><img src="{key}.{extension}"></a>'
                     f'<p><a href="{key}.html">打开报告HTML</a> · <a href="{key}.svg">单独看关系图</a> · <a href="{key}.json">测试数据</a></p></section>')
        print(key, 'members', count, 'overview', shown, 'roles', role_count, dimensions)
    gallery = '''<!doctype html><meta charset="utf-8"><title>群关系连线 · 检查样例</title>
    <style>body{margin:32px auto;max-width:1500px;padding:0 20px;background:#0b1220;color:#dfeaff;font:16px/1.7 system-ui}a{color:#a9d1ff}section{margin:32px 0;border-top:1px solid #394761;padding-top:12px}img{display:block;max-width:100%;background:#101b2d}li{margin:6px 0}</style>
    <h1>群关系连线 · 检查样例</h1><p>全部为可重复生成的模拟数据；点击图片可放大。这里是本地验收文件，不是插件后台页面。</p>
    <ol><li>连线应平滑、直接连接双方，没有绕向空位的尖角或折返。</li><li>关系名称在对应连线上，直接使用父亲、损友等名称。</li><li>头像与昵称分开，长昵称、重名仍可辨认；连接少的成员不挤在同一个角落。</li><li>54人样例只画12人概览，右侧保留20条关系；统计人数仍为54。</li><li>复杂关系仍可能有交叉，检查每条线能否追踪到双方。</li></ol>
    '''+''.join(cards)
    (args.output/'index.html').write_text(gallery, encoding='utf-8')
    (args.output/'检查说明.txt').write_text('打开 index.html 按页面中的五项标准检查。\n样例包括5人、12人、54人、单人中心、分组重名与空数据。\n每组同时提供PNG、HTML、SVG和JSON，可放大或核对原始模拟数据。\n生成方式：python scripts/layout_samples.py OUTPUT_DIR --endpoint http://nekro_html2img:3000\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
