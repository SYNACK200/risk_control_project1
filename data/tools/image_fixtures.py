"""Procedural test fixtures, not real banking documents or OCR outputs."""
from pathlib import Path
import json
from PIL import Image, ImageDraw

folder = Path(__file__).resolve().parents[1] / 'inputs' / 'demo_images'
folder.mkdir(exist_ok=True)
manifest = []
for carrier in ('photo', 'scan', 'screenshot'):
    for index in range(3):
        background = (236, 232, 220) if carrier == 'photo' else (250, 250, 250)
        image = Image.new('RGB', (1200, 1600), background)
        draw = ImageDraw.Draw(image)
        draw.text((100, 100), 'SYNTHETIC DEMO - NO REAL CUSTOMER DATA', fill=(0, 0, 0))
        for row in range(10):
            y = 250 + row * 90
            draw.line((100, y, 1100, y), fill=(100, 100, 100))
            draw.text((100, y + 20), 'DEMO ROW %02d AMOUNT %d.00' % (row, row + 1), fill=(0, 0, 0))
        if carrier == 'screenshot':
            draw.rectangle((0, 0, 1200, 60), fill=(30, 30, 30))
        if carrier == 'photo':
            image = image.rotate(index + 1, fillcolor=background)
        filename = '%s-%d.png' % (carrier, index + 1)
        image.save(str(folder / filename))
        manifest.append({'file': filename, 'width': 1200, 'height': 1600, 'synthetic': True, 'intended_style': carrier, 'classifier_verified': False})
(folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Generated 9 synthetic PNG fixtures; carrier classifier NOT verified')
