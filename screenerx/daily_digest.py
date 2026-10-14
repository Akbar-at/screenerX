"""Two-message daily Telegram digest; detailed numbers remain in a single PDF."""
import hashlib
import json
from pathlib import Path
from .reporting import render_top,RENDER_LOCK


def prepare_daily_digest(repository,output,request_date):
    import gc
    report=repository.report
    signature={'version':'daily-digest-v1','request_date':request_date,'as_of':report['as_of'],
               'inputs':report.get('input_files'), 'config':report.get('config_sha256'),
               'selected':report['top10'],'idx':report.get('idx_screening')}
    folder=Path(output)/hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
    folder.mkdir(parents=True,exist_ok=True)
    assets=render_top(repository,folder,include_pdf=False)
    gc.collect()
    pdf=folder/('daily-'+report['as_of']+'.pdf')
    # Append one image at a time: avoid retaining an entire raster report in RAM.
    with RENDER_LOCK:
        if not pdf.exists():
            from PIL import Image
            temporary=pdf.with_suffix('.tmp')
            pages=[assets['png']]+[Path(row['chart']) for row in assets['analyses']]
            for index,path in enumerate(pages):
                with Image.open(path) as raster:
                    with raster.convert('RGB') as page:
                        page.save(temporary,format='PDF',append=index>0,resolution=150,quality=95)
            temporary.replace(pdf)
    selected=report['top10'];ready=sum(bool(c.get('execution_readiness',{}).get('reward_risk_passed')) for c in selected)
    caption=(f"Daily screening | {request_date}\nSesi data: {report['as_of']}\n"
             f"Shortlist riset: {len(selected)}/{report['requested_slots']} | Setup R/R lolos: {ready}/{len(selected)}\n"
             'Kode: '+(', '.join(c['ticker'] for c in selected) or 'Belum ada kandidat')+'\n')
    if selected and not ready:caption+='Sikap: tunggu setup baru; R/R belum memenuhi profil.\n'
    idx=report.get('idx_screening',{}).get('counts')
    if idx:caption+=f"IDX foreign volume: {idx['available']}/{report['universe_count']} kode tersedia.\n"
    caption+='Detail angka & grafik ada di PDF. /stock KODE untuk analisis satu saham.\nValuasi belum direview; broker net per saham ON_HOLD.'
    if len(caption)>1024:raise ValueError('Daily digest exceeds Telegram caption limit')
    return [{'kind':'photo','path':str(assets['png']),'caption':caption},
            {'kind':'document','path':str(pdf),'caption':'Grafik & tabel lengkap | sesi '+report['as_of']}]
