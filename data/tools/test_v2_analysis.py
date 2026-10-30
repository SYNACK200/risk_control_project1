"""Actual team parsing/risk/report chain with an in-memory synthetic PDF. No DB."""
from pathlib import Path
import sys
DATA=Path(__file__).resolve().parents[1]
ROOT=Path('C:/Users/姜佳庆/AppData/Local/Temp/risk_control_project1-v2-e9baadf')
sys.path[:0]=[str(DATA),str(ROOT/'backend'),str(ROOT)]
from v2.runtime import synthetic_pdf
from services.analysis import run_analysis
from algorithm.algo.preread import run_preread

if __name__=='__main__':
    pdf=synthetic_pdf()
    pre=run_preread(pdf)
    result=run_analysis(pdf,preread=pre)
    assert pre.verdict!='reject' and result['txn_count']==3
    assert len(result['metrics'])==40 and len(result['report']['layers'])==4
    assert result['transactions'][0]['amount']=='12500.00'
    print('Actual synthetic PDF -> parse -> 40 metrics -> 4 report layers PASS; no DB or HTTP request')
