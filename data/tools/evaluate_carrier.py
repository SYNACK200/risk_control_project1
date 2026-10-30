"""Offline evaluator of owner-provided fixture predictions; NOT a classifier."""
import argparse
import hashlib
import json
from pathlib import Path


def evaluate(expected, document):
    if not isinstance(document.get('producer_version'),str) or not document['producer_version']:
        raise ValueError('Classifier producer/version evidence required')
    predictions=document.get('predictions',[])
    if len(predictions)!=len(expected) or {item['file'] for item in predictions}!=set(expected):
        raise ValueError('Missing/duplicate/unknown fixture prediction')
    mismatches=[]
    for item in predictions:
        reference=expected[item['file']]
        if item.get('sha256')!=reference['sha256']: raise ValueError('Fixture content hash mismatch')
        if item.get('carrier')!=reference['carrier']: mismatches.append(item['file'])
    return {'fixtures':len(expected),'producer_version':document['producer_version'],
            'mismatches':mismatches,'accepted':not mismatches}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--predictions',type=Path,required=True)
    args=parser.parse_args()
    folder=Path(__file__).resolve().parents[1]/'inputs/demo_images'
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    expected={}
    for item in manifest:
        path=folder/item['file']
        if path.resolve().parent!=folder.resolve(): raise ValueError('Unsafe fixture path')
        expected[item['file']]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'carrier':'screenshot' if item['intended_style']=='screenshot' else 'image'}
    result=evaluate(expected,json.loads(args.predictions.read_text(encoding='utf-8')))
    print(json.dumps(result))
    if not result['accepted']: raise SystemExit(1)


if __name__ == '__main__': main()
