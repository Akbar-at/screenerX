"""IDX supplemental numerical dashboard. No directional stock-by-broker claims."""
import hashlib
import json
import math
import textwrap
from pathlib import Path
from .idx_source import scalar

VERSION='idx-daily-v1'


def idx_tables(data):
    from .reporting import money,percent
    def value(v): return '-' if scalar(v) is None else f'{scalar(v):,.0f}'.replace(',','.')
    def price(v): return '-' if scalar(v) is None or scalar(v)<=0 else money(scalar(v))
    tables=[('Sumber & cakupan',[
        ('Sesi harga',data['as_of']),('Sumber','IDX / BEI'),('Broker net per saham','ON_HOLD'),
        *[(name,info['status']+(' | '+str(info['records'])+' rows' if 'records' in info else '')) for name,info in data['datasets'].items()]])]
    row=data.get('stocks')
    if row:
        tables.append(('Aktivitas asing - volume',[
            ('Foreign buy',value(row['ForeignBuy'])),('Foreign sell',value(row['ForeignSell'])),
            ('Net foreign volume',value(data['net_foreign_volume'])),
            ('Satuan','Saham; bukan nilai rupiah'),('Sesi',data['as_of'])]))
        tables.append(('Transaksi harian IDX',[
            ('Open / high',price(row.get('OpenPrice'))+' / '+price(row.get('High'))),
            ('Low / close',price(row.get('Low'))+' / '+price(row.get('Close'))),
            ('Volume saham',value(row['Volume'])),('Nilai transaksi dilaporkan',money(row['Value'])),
            ('Frekuensi',value(row['Frequency'])),('Non-regular volume',value(row.get('NonRegularVolume'))),
            ('Non-regular value',money(scalar(row.get('NonRegularValue')))),
            ('Non-regular frequency',value(row.get('NonRegularFrequency')))]))
        tables.append(('Bid / offer snapshot harian',[
            ('Bid',price(row.get('Bid'))),('Offer',price(row.get('Offer'))),
            ('Spread snapshot',percent(data.get('snapshot_spread'))),
            ('Tanggal',data['as_of']),('Timestamp quote','Tidak tersedia; bukan live quote')]))
    brokers=data.get('brokers')
    if brokers is not None:
        total=data.get('broker_total_value',0)
        tables.append(('Broker - seluruh pasar',[
            ('Cakupan','Seluruh bursa; bukan saham ini'),('Total nilai broker dilaporkan',money(total)),
            *[(str(r['IDFirm'])+' '+str(r.get('FirmName',''))[:23],money(r['Value'])+' / '+(percent(r['Value']/total) if total else '-')) for r in brokers],
            ('Persentase','Porsi dari total nilai broker'),('Arah beli / jual','Tidak tersedia')]))
    if 'profiles' in data['datasets']:
        row=data.get('profiles')
        rows=[('Status',data['datasets']['profiles']['status'])]
        if row:
            rows.extend([(label,str(row.get(key) or '-')) for label,key in
                         [('Emiten','NamaEmiten'),('Sektor','Sektor'),('Subsektor','SubSektor'),('Papan','PapanPencatatan')]])
            rows.append(('Diambil',data['evidence']['profiles']['captured_at'][:19]))
        tables.append(('Profil emiten',rows))
    if 'ratios' in data['datasets']:
        row=data.get('ratios');rows=[('Status',data['datasets']['ratios']['status'])]
        if row:
            params=data['evidence']['ratios']['params']
            rows.append(('Periode diminta',str(params['periodYear'])+' Q'+str(params['periodQuarter'])+' '+params['type']))
            rows.append(('Diambil',data['evidence']['ratios']['captured_at'][:19]))
            for label,key in [('Tanggal fsDate sumber','fsDate'),('Tahun fiskal berakhir','fiscalYearEnd'),
                              ('PER (nilai sumber)','per'),('PBV (nilai sumber)','priceBV'),('ROE (nilai sumber)','roe'),
                              ('ROA (nilai sumber)','roa'),('EPS (nilai sumber)','eps'),('DER (nilai sumber)','deRatio'),
                              ('NPM (nilai sumber)','npm'),('Opini audit','opini')]:
                v=row.get(key);rows.append((label,'-' if v is None or v=='' else str(v)))
            rows.append(('Periode / unit','Belum diverifikasi untuk model'))
        tables.append(('Rasio IDX - referensi',rows))
    return tables


def idx_text(data):
    from .reporting import text_table
    parts=[f"{data['ticker']} | {data['as_of']} | IDX DATA TAMBAHAN"]
    parts.extend(title+'\n'+text_table(rows) for title,rows in idx_tables(data))
    parts.append('Foreign buy/sell adalah volume saham, bukan nilai rupiah. Aktivitas broker mencakup seluruh pasar dan tidak menunjukkan akumulasi broker pada saham ini. Broker net per saham tetap ON_HOLD. Bid/offer adalah snapshot harian, bukan quote live. Rasio hanya referensi; periode/unit harus diverifikasi dan tidak mengganti input DDM/RIM/EVA.')
    if data.get('errors'): parts.append('Data belum tersedia: '+'; '.join(k+': '+v for k,v in data['errors'].items()))
    return '\n\n'.join(parts)


def render_idx(data,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from .reporting import RENDER_LOCK,GREEN,INK
    signature={'version':VERSION,'ticker':data['ticker'],'as_of':data['as_of'],'evidence':data['evidence'],'datasets':data['datasets']}
    folder=Path(output)/hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
    folder.mkdir(parents=True,exist_ok=True);stem=data['ticker']+'-'+data['as_of']
    png=folder/(stem+'-chart.png');pdf=folder/(stem+'.pdf');tables=idx_tables(data)
    if not png.exists() or not pdf.exists():
        heights=[max(len(rows) for _,rows in tables[i:i+2])*.28+1.0 for i in range(0,len(tables),2)]
        height=2.0+sum(heights)+1.4
        with RENDER_LOCK:
            fig=plt.figure(figsize=(12,height),facecolor='white')
            fig.text(.055,1-.35/height,'ScreenX | '+data['ticker']+' | IDX',fontsize=21,color=GREEN,weight='bold',va='top')
            fig.text(.055,1-.9/height,'Sesi '+data['as_of']+' | broker net per saham ON_HOLD',fontsize=11,color=INK,va='top')
            top=1-1.5/height
            for index,(title,rows) in enumerate(tables):
                pair=index//2;x=.055+(index%2)*.455;y=top-sum(heights[:pair])/height;panel_height=heights[pair]-.55
                fig.text(x,y,title,fontsize=11,color=GREEN,weight='bold',va='top')
                ax=fig.add_axes([x,y-(panel_height+.3)/height,.435,panel_height/height]);ax.axis('off')
                wrapped=[(textwrap.fill(str(label),width=27),textwrap.fill(str(value),width=30)) for label,value in rows]
                table=ax.table(cellText=wrapped,colLabels=['Metrik','Nilai'],colWidths=[.48,.52],cellLoc='left',bbox=[0,0,1,1])
                table.auto_set_font_size(False);table.set_fontsize(9)
                for (r,c),cell in table.get_celld().items():
                    cell.set_facecolor(GREEN if r==0 else '#eef5f0' if r%2 else '#f8faf9');cell.set_edgecolor('white');cell.get_text().set_color('white' if r==0 else INK)
            fig.text(.055,1.0/height,'Foreign flow: volume saham. Broker: total seluruh pasar, tanpa arah beli/jual.\nBid/offer: snapshot harian. Rasio referensi: periode/unit belum diverifikasi untuk valuasi.',fontsize=9,color=INK,va='top')
            fig.savefig(png,dpi=150,facecolor='white');fig.savefig(pdf,facecolor='white');plt.close(fig)
    text=idx_text(data);(folder/(stem+'.txt')).write_text(text,encoding='utf-8')
    return {'chart':png,'pdf':pdf,'text':text}
