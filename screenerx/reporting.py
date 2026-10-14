"""Evidence-based Indonesian research narratives and shareable PNG/PDF reports."""
import argparse
import json
import math
import re
import textwrap
import threading
from pathlib import Path

from .engine import InputError, load_prices
from .fetch import symbol_for

RENDER_LOCK = threading.Lock()
GREEN = '#176148'
INK = '#19352e'
MUTED = '#61726b'
RED = '#ba493e'
RENDERER_VERSION = 'selectable-analysis-idx-v5'


def money(value):
    return 'belum tersedia' if value is None else 'Rp' + f'{value:,.0f}'.replace(',', '.')


def percent(value):
    return 'belum tersedia' if value is None else f'{value:.1%}'


def number(value,places=2,suffix=''):
    return '-' if value is None else f'{value:.{places}f}'+suffix


def metric_tables(company):
    """One formatted data source shared by Telegram tables and the chart image."""
    t=company.get('technical') or {}; v=company.get('valuation') or {}; p=company.get('plan') or {}
    def price(value): return '-' if value is None else money(value)
    def pct(value,places=1): return '-' if value is None else f'{value:.{places}%}'
    def model(method):
        status=company.get('models',{}).get(method,{}).get('status')
        if status=='NOT_APPLICABLE': return 'Tidak berlaku'
        return price(v.get(method)) if v.get(method) is not None else 'Tidak tersedia'
    minimum=p.get('minimum_net_rr')
    if minimum is None:
        match=next((re.search(r'Estimated net reward/risk below ([0-9.]+)',reason)
                    for reason in p.get('risk_reasons',[]) if re.search(r'Estimated net reward/risk below ([0-9.]+)',reason)),None)
        if match: minimum=float(match.group(1))
    liquidity=((company.get('quality') or {}).get('liquidity_floor') or {}).get('evidence') or {}
    costs=p.get('cost_assumptions') or {}
    required=company.get('required_models') or []
    model_count=sum(v.get(m) is not None for m in required)
    return [
        ('Teknikal',[
            ('Close',price(company.get('close'))),('SMA20',price(t.get('sma20'))),('SMA60',price(t.get('sma60'))),
            ('MACD',number(t.get('macd'))),('Signal MACD',number(t.get('macd_signal'))),
            ('RSI',number(t.get('rsi'),1)),('Stoch K',number(t.get('stoch_k'),1)),('Stoch D',number(t.get('stoch_d'),1)),
            ('Volume / median',number(t.get('volume_multiple'),2,'x')),('ATR',number(t.get('atr'))),('Return 20 sesi',pct(t.get('return20')))]),
        ('Fundamental & valuasi',[
            ('DDM',model('ddm')),('RIM',model('rim')),('EVA',model('eva')),('Rata-rata model',price(v.get('fair_value'))),
            ('MOS',pct(v.get('current_mos'))),('Dispersi',pct(v.get('dispersion'))),
            ('Bear',price(v.get('bear_value'))),('Base',price(v.get('fair_value'))),('Bull',price(v.get('bull_value'))),
            ('Model tersedia',f'{model_count}/{len(required)}' if required else '-'),
            ('Laporan tahunan',v.get('statement_date') or '-'),
            ('Kurs '+v.get('financial_currency','')+'/IDR' if v.get('financial_currency') else 'Kurs ke IDR',number(v.get('fx_rate'),2)),('Tanggal kurs',v.get('fx_date') or '-')]),
        ('Strategi & level',[
            ('Entry',price(p.get('entry_price'))),('TP1',price(p.get('tp1_price'))),('TP2',price(p.get('tp2_price'))),
            ('Stop',price(p.get('stop_loss_price'))),('Support',price(p.get('support'))),('Resistance',price(p.get('resistance'))),
            ('Gross R/R',number(p.get('gross_rr'),2,'x')),('Net R/R',number(p.get('net_rr'),2,'x')),
            ('R/R minimum',number(minimum,2,'x'))]),
        ('Likuiditas & asumsi biaya',[
            ('Median transaksi',price(company.get('median_turnover_idr'))),('Minimum profil',price(liquidity.get('minimum'))),
            ('Fee beli',pct(costs.get('buy_fee'),2)),('Fee jual',pct(costs.get('sell_fee'),2)),
            ('Slippage entry',pct(costs.get('entry_slippage'),2)),('Slippage target',pct(costs.get('target_slippage'),2)),
            ('Slippage stop',pct(costs.get('stop_slippage'),2)),('Pajak efektif',pct(v.get('tax_rate'),2)),
            ('Payout model',pct(v.get('payout_ratio'))),('Skor riset',number((company.get('score') or {}).get('total'),1,'/100'))])]


def text_table(rows):
    label_width=max(len('Metrik'),max(len(label) for label,value in rows))
    value_width=max(len('Nilai'),max(len(str(value)) for label,value in rows))
    lines=[f"{'Metrik':<{label_width}} | {'Nilai':>{value_width}}",'-'*label_width+'-+-'+'-'*value_width]
    lines.extend(f'{label:<{label_width}} | {str(value):>{value_width}}' for label,value in rows)
    return '```\n'+'\n'.join(lines)+'\n```'


def risk_text(reason):
    translations={
        'Liquidity below threshold or missing':'Likuiditas di bawah batas profil atau belum tersedia.',
        'Missing an applicable valuation model':'Ada model valuasi yang belum tersedia.',
        'Incomplete sensitivity for applicable models':'Skenario sensitivitas model belum lengkap.',
        'No positive aligned annual common dividends':'Dividen tahunan positif yang selaras belum tersedia.',
    }
    if reason.startswith('Estimated net reward/risk below '): return 'Net R/R belum memenuhi minimum profil.'
    return translations.get(reason,reason)


def recommendation(company):
    technical=company.get('technical') or {}
    plan=company.get('plan') or {}
    if not company.get('coverage_complete'):
        return 'DATA BELUM LENGKAP', 'Lengkapi data sebelum mempertimbangkan entry.'
    if not company.get('quality_passed'):
        return 'KAJIAN LANJUTAN', 'Kandidat belum lolos pemeriksaan kualitas; jangan memakai estimasi sebagai dasar entry.'
    if plan.get('net_rr') is None or not company.get('execution_readiness',{}).get('reward_risk_passed'):
        return 'TUNGGU SETUP BARU', 'Lewatkan rencana entry ini; imbalan terhadap risiko setelah biaya belum memenuhi minimum profil.'
    close=company.get('close')
    trend=(close is not None and close > technical.get('sma20', math.inf)
           and technical.get('sma20',0)>technical.get('sma60',math.inf)
           and technical.get('macd',0)>technical.get('macd_signal',math.inf))
    if not trend:
        return 'TUNGGU KONFIRMASI', 'Pantau pemulihan tren dan konfirmasi harga; belum ada konfirmasi entry dari kondisi saat ini.'
    return 'PANTAU BREAKOUT', 'Pantau penembusan level entry dengan volume; rencana tetap bersyarat dan memerlukan pemeriksaan data serta eksekusi.'


def narrative(company):
    if company.get('_analysis_modes'): return scoped_narrative(company)
    ticker=company['ticker']; close=company.get('close'); t=company.get('technical') or {}
    v=company.get('valuation') or {}; plan=company.get('plan') or {}
    label,action=recommendation(company)
    tables=dict(metric_tables(company))
    if t and close is not None and all(t.get(k) is not None for k in ('sma20','sma60','macd','macd_signal')):
        relation='di atas' if close>t['sma20'] else 'di bawah atau sama dengan'
        trend='menguat' if t['sma20']>t['sma60'] else 'belum menguat'
        momentum='di atas' if t['macd']>t['macd_signal'] else 'di bawah atau sama dengan'
        technical=f'Harga {relation} rata-rata pendek; struktur rata-rata pendek/panjang {trend}. MACD {momentum} signal.'
    else: technical='Riwayat harga/indikator belum memadai untuk analisis teknikal yang lengkap.'
    valuation=(f"Sumber: {v.get('financial_provider','yfinance')}; angka model dalam IDR per saham. "
               'Estimasi memakai asumsi pertumbuhan dan diskonto; skenario bukan target yang dijamin.') if v else 'Valuasi belum tersedia; data laporan keuangan yang cocok belum lengkap.'
    sections=[
        ('Teknikal & struktur harga',text_table(tables['Teknikal'])+'\n\n'+technical),
        ('Fundamental & valuasi',text_table(tables['Fundamental & valuasi'])+'\n\n'+valuation),
        ('Broker flow','ON_HOLD. Data transaksi broker belum terintegrasi; akumulasi/distribusi asing atau institusi belum dapat dikonfirmasi.'),
        ('Strategi & invalidasi',text_table(tables['Strategi & level'])+'\n\n'+action+' Level berasal dari OHLC historis dan perlu dihitung ulang jika harga berubah. Rencana gugur jika harga melewati stop; ini bukan bukti entry telah terjadi.'),
        ('Likuiditas & asumsi biaya',text_table(tables['Likuiditas & asumsi biaya'])+'\n\nFee dan slippage mengikuti asumsi tersimpan; payout mengikuti input model. Tarif broker belum diverifikasi.')]
    issues=company.get('failed_quality_checks',[])+company.get('missing_inputs',[])
    risks=[risk_text(x['reason']) for x in issues][:3]+[risk_text(x) for x in plan.get('risk_reasons',[])[:2]]
    risks+=['Valuasi belum direview; corporate actions dan bid/offer belum diverifikasi.']
    sections.append(('Risiko utama',' '.join(dict.fromkeys(risks))))
    return {'ticker':ticker,'as_of':company['as_of'],'label':label,'action':action,'sections':sections,
            'tables':metric_tables(company),
            'text':f"{ticker} | {company['as_of']} | {label}\n\n"+'\n\n'.join(title+'\n'+body for title,body in sections)}


def scoped_narrative(company):
    modes=company['_analysis_modes']; components=company['_analysis_components']
    base=dict(company); base.pop('_analysis_modes'); full=narrative(base)
    tables=dict(metric_tables(company)); selected=[]; sections=[]
    titles={'technical':'Teknikal','fundamental':'Fundamental & valuasi','broker':'Broker flow'}
    statuses=[(titles[m],components[m]['status']) for m in modes]
    selected.append(('Status pipeline',statuses))
    sections.append(('Pipeline dipilih',text_table(statuses)))
    if 'technical' in modes:
        selected.extend([(k,tables[k]) for k in ('Teknikal','Strategi & level')])
        sections.extend([full['sections'][0],('Strategi & invalidasi',text_table(tables['Strategi & level'])+'\n\n'+components['technical']['assessment']+' Level OHLC bersyarat; periksa net R/R, likuiditas dan bid/offer sebelum entry.')])
        costs=[row for row in tables['Likuiditas & asumsi biaya'] if row[0] not in ('Pajak efektif','Payout model','Skor riset')]
        selected.append(('Likuiditas & biaya',costs));sections.append(('Likuiditas & biaya',text_table(costs)))
    if 'fundamental' in modes:
        selected.append(('Fundamental & valuasi',tables['Fundamental & valuasi']))
        assumptions=[row for row in tables['Likuiditas & asumsi biaya'] if row[0] in ('Pajak efektif','Payout model')]
        selected.append(('Asumsi fundamental',assumptions))
        sections.extend([full['sections'][1],('Asumsi fundamental',text_table(assumptions)+'\n\n'+components['fundamental']['assessment'])])
    if 'broker' in modes:
        selected.append(('Broker flow',[('Status','ON_HOLD'),('Sumber','Belum terintegrasi')]))
        sections.append(('Broker flow',text_table(selected[-1][1])+'\n\nON_HOLD. '+components['broker']['assessment']))
        if company.get('_idx_data'):
            from .idx_reporting import idx_tables
            for title,rows in idx_tables(company['_idx_data']):
                selected.append((title,rows));sections.append((title,text_table(rows)))
            sections.append(('Batasan IDX','Aktivitas asing adalah volume saham. Broker mencakup seluruh bursa, bukan broker net saham ini. Bid/offer merupakan snapshot harian, bukan quote live.'))
    statuses_only=[c['status'] for c in components.values()]
    label='ON_HOLD' if modes==('broker',) else 'ANALISIS PARSIAL' if any(x in ('UNAVAILABLE','PARTIAL_ESTIMATES','ON_HOLD') for x in statuses_only) else 'ANALISIS TERSEDIA'
    action=' | '.join(titles[m]+': '+components[m]['assessment'] for m in modes)
    return {'ticker':company['ticker'],'as_of':company['as_of'],'label':label,'action':action,
            'sections':sections,'tables':selected,
            'text':f"{company['ticker']} | {company['as_of']} | {label}\nMode: {' + '.join(modes)}\n\n"+'\n\n'.join(t+'\n'+b for t,b in sections)}


def scoped_figure(company,bars):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    info=scoped_narrative(company); technical='technical' in company['_analysis_modes']
    count=len(info['tables']); rows=math.ceil(count/2)
    height=3.5+rows*3.5+(4 if technical else 0)
    fig=plt.figure(figsize=(10,height),facecolor='white')
    fig.text(.055,1-.35/height,'screenerX | '+company['ticker'],fontsize=22,color=GREEN,weight='bold',va='top')
    fig.text(.055,1-.85/height,company['as_of']+' | '+' + '.join(company['_analysis_modes']),fontsize=11,color=INK,va='top')
    fig.text(.055,1-1.2/height,info['label'],fontsize=12,color=RED,va='top')
    top=1-1.75/height
    if technical:
        ax=fig.add_axes([.08,top-2.7/height,.85,2.7/height]);view=bars[-90:]
        if view:
            for i,b in enumerate(view):
                color=GREEN if b['close']>=b['open'] else RED
                ax.plot([i,i],[b['low'],b['high']],color=color,lw=.8)
                ax.add_patch(Rectangle((i-.3,min(b['open'],b['close'])),.6,max(abs(b['close']-b['open']),b['close']*.0005),facecolor=color))
            offset=len(bars)-len(view)
            for period in (20,60):
                ax.plot(range(len(view)),[sum(b['close'] for b in bars[j-period+1:j+1])/period if j>=period-1 else None for j in range(offset,len(bars))],label=f'SMA{period}')
            marks=sorted(set([0,len(view)//2,len(view)-1]));ax.set_xticks(marks,[view[i]['date'].strftime('%d/%m') for i in marks])
            ax.legend(fontsize=8);ax.grid(alpha=.15)
        else: ax.text(.5,.5,'Riwayat harga belum tersedia',transform=ax.transAxes,ha='center')
        top-=3.25/height
    for i,(title,data) in enumerate(info['tables']):
        x=.055+(i%2)*.455;y=top-(i//2)*3.5/height
        fig.text(x,y,title,fontsize=11,color=GREEN,weight='bold',va='top')
        panel=fig.add_axes([x,y-3.1/height,.435,2.8/height]);panel.axis('off')
        table=panel.table(cellText=data,colLabels=['Metrik','Nilai'],colWidths=[.53,.47],cellLoc='left',bbox=[0,0,1,1]);table.auto_set_font_size(False);table.set_fontsize(10)
        for (r,c),cell in table.get_celld().items():
            cell.set_facecolor(GREEN if r==0 else '#eef5f0' if r%2 else '#f8faf9');cell.set_edgecolor('white');cell.get_text().set_color('white' if r==0 else INK)
    fig.text(.055,.8/height,textwrap.fill(info['action'],width=115),fontsize=9,color=INK,va='top')
    return fig


class ReportRepository:
    def __init__(self,run_dir,prices_path):
        self.run_dir=Path(run_dir)
        self.report=json.loads((self.run_dir/'core-run.json').read_text(encoding='utf-8'))
        self.companies={x['ticker']:x for x in self.report['companies']}
        self.prices=load_prices(prices_path)
        self.prices_path=Path(prices_path)

    def company(self,ticker):
        ticker,_=symbol_for(ticker)
        if ticker not in self.companies: raise InputError(f'{ticker} belum ada di run ini; gunakan /stock {ticker} live jika live lookup diaktifkan.')
        return self.companies[ticker]

    def bars(self,ticker):
        asof=self.report['as_of']
        return [r for r in self.prices.get(ticker,[]) if r['date'].isoformat()<=asof]


def figure(company,bars):
    if company.get('_analysis_modes'): return scoped_figure(company,bars)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import FuncFormatter
    fig=plt.figure(figsize=(10,16),facecolor='white')
    info=narrative(company); t=company.get('technical') or {}; v=company.get('valuation') or {}; plan=company.get('plan') or {}
    fig.text(.055,.973,'screenerX',fontsize=23,fontweight='bold',color=GREEN)
    fig.text(.945,.976,'RISET SAHAM INDONESIA',ha='right',fontsize=10,color=MUTED)
    fig.text(.945,.960,company['as_of']+' | Yahoo / yfinance',ha='right',fontsize=10,color=INK)
    fig.text(.055,.930,company['ticker'],fontsize=31,fontweight='bold',color=INK)
    fig.text(.055,.907,info['label'],fontsize=13,fontweight='bold',color=RED if info['label']!='PANTAU BREAKOUT' else GREEN)
    cards=[('CLOSE',money(company.get('close'))),('MARGIN OF SAFETY',percent(v.get('current_mos'))),
           ('NET R/R',number(plan.get('net_rr'),2,'x')),('SKOR RISET',number((company.get('score') or {}).get('total'),1,'/100'))]
    for i,(title,value) in enumerate(cards):
        x=.055+i*.225
        fig.add_artist(Rectangle((x,.852),.215,.046,transform=fig.transFigure,facecolor='#eef5f0',edgecolor='none'))
        fig.text(x+.010,.882,title,fontsize=8,color=MUTED)
        fig.text(x+.010,.863,value,fontsize=16,fontweight='bold',color=INK)
    ax=fig.add_axes([.085,.655,.85,.184]); volume=fig.add_axes([.085,.612,.85,.033],sharex=ax)
    view=bars[-90:]; ax.set_facecolor('#f6f9f7')
    if view:
        for i,b in enumerate(view):
            color=GREEN if b['close']>=b['open'] else RED
            ax.plot([i,i],[b['low'],b['high']],color=color,linewidth=.8)
            height=max(abs(b['close']-b['open']),b['close']*.0005)
            ax.add_patch(Rectangle((i-.3,min(b['open'],b['close'])),.6,height,facecolor=color,edgecolor=color,linewidth=.5))
            volume.bar(i,b['volume'],color=color,width=.7)
        offset=len(bars)-len(view)
        for period,color in ((20,'#d49723'),(60,'#687eab')):
            means=[sum(b['close'] for b in bars[max(0,j-period+1):j+1])/period if j>=period-1 else None for j in range(offset,len(bars))]
            ax.plot(range(len(view)),means,color=color,linewidth=1.2,label=f'SMA{period}')
        for key,label,color in (('entry_price','Entry',GREEN),('stop_loss_price','Stop',RED),('tp1_price','TP1','#5668a2'),('tp2_price','TP2','#956ab1')):
            value=plan.get(key)
            lo=min(b['low'] for b in view); hi=max(b['high'] for b in view)
            if value is not None and lo*.9<=value<=hi*1.1:
                ax.axhline(value,color=color,linestyle='--',linewidth=.8,label=f'{label} {value:,.0f}')
        marks=sorted(set(list(range(0,len(view),max(1,len(view)//5)))+[len(view)-1]))
        volume.set_xticks(marks,[view[i]['date'].strftime('%d/%m') for i in marks],fontsize=8)
        ax.legend(loc='upper left',fontsize=7,framealpha=.9,ncol=2)
    else:
        ax.text(.5,.5,'Riwayat harga belum tersedia',transform=ax.transAxes,ha='center',color=MUTED)
        ax.set_axis_off(); volume.set_axis_off()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda val,pos:f'{val:,.0f}'))
    ax.tick_params(labelsize=8,labelbottom=False); ax.grid(alpha=.12)
    volume.tick_params(axis='y',left=False,labelleft=False); volume.set_ylabel('Vol',fontsize=7)
    for axis in (ax,volume):
        for spine in axis.spines.values(): spine.set_visible(False)
    for (title,rows),(x,y,width,height) in zip(info['tables'],[
        (.055,.344,.435,.230),(.510,.344,.435,.230),(.055,.094,.435,.230),(.510,.094,.435,.230)]):
        fig.text(x,y+height+.010,title.upper(),fontsize=11,fontweight='bold',color=GREEN)
        panel=fig.add_axes([x,y,width,height]); panel.axis('off')
        table=panel.table(cellText=rows,colLabels=['Metrik','Nilai'],cellLoc='left',colLoc='left',
                          colWidths=[.53,.47],bbox=[0,0,1,1])
        table.auto_set_font_size(False); table.set_fontsize(10.5)
        for (row,col),cell in table.get_celld().items():
            cell.set_edgecolor('white'); cell.set_linewidth(1)
            cell.set_facecolor(GREEN if row==0 else '#eef5f0' if row%2 else '#f8faf9')
            cell.get_text().set_color('white' if row==0 else INK)
            if col==1 and row: cell.get_text().set_ha('right')
            if row==0: cell.get_text().set_fontweight('bold')
    fig.text(.055,.074,textwrap.fill(info['action'],width=105),fontsize=10,color=INK,va='top',linespacing=1.3)
    fig.text(.055,.028,'ESTIMASI BELUM DIREVIEW | BROKER FLOW ON_HOLD | LEVEL BERSYARAT',fontsize=9,color=RED)
    fig.text(.945,.015,'Harga/model: Rp per saham | Biaya & payout: input model',ha='right',fontsize=8,color=MUTED)
    return fig


def summary_figure(report):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(10,11),facecolor='white')
    fig.text(.07,.93,'screenerX | Top 10',fontsize=26,fontweight='bold',color=GREEN)
    fig.text(.07,.892,f"Sesi {report['as_of']}  |  {report['selected_count']} kandidat lolos dari {report['universe_count']} kode",fontsize=12,color=INK)
    ax=fig.add_axes([.07,.23,.86,.60]); ax.axis('off')
    rows=[]
    for c in report['top10']:
        v=c.get('valuation') or {}
        rows.append([c['rank'],c['ticker'],f"{c['score']['total']:.1f}",money(c.get('close')),percent(v.get('current_mos')),recommendation(c)[0]])
    while len(rows)<report['requested_slots']:
        rows.append([len(rows)+1,'Belum terisi','-','-','-','Belum ada kandidat lolos'])
    table=ax.table(cellText=rows,colLabels=['Rank','Kode','Skor','Close','MOS','Sikap riset'],cellLoc='left',colLoc='left',loc='upper center',colWidths=[.07,.1,.08,.15,.10,.50])
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1,2.8)
    for (row,col),cell in table.get_celld().items():
        cell.set_edgecolor('white')
        cell.set_facecolor(GREEN if row==0 else '#eef5f0' if row%2 else '#f8faf9')
        cell.get_text().set_color('white' if row==0 else INK)
    fig.text(.07,.18,f"{report['coverage_complete_count']} perusahaan memiliki cakupan riset lengkap. {report['unfilled_slots']} slot belum terisi.",fontsize=11,color=INK)
    fig.text(.07,.13,'Ranking riset tidak berarti sinyal beli. Periksa konfirmasi harga dan net R/R.\nValuasi belum direview; broker flow ON_HOLD.',fontsize=11,color=MUTED,linespacing=1.8)
    fig.text(.07,.045,'Data: Yahoo / yfinance | Profil fundamental 50% + teknikal 40% + likuiditas 10%',fontsize=9,color=MUTED)
    return fig


def save_chart(fig,company,bars,path):
    """The Telegram chart keeps every numerical table alongside the price axes."""
    fig.savefig(path,dpi=160,facecolor='white')


def render_stock(company,bars,output):
    import matplotlib.pyplot as plt
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    stem=f"{company['ticker']}-{company['as_of']}"
    with RENDER_LOCK:
        fig=figure(company,bars)
        fig.savefig(output/(stem+'.png'),dpi=160,facecolor='white')
        fig.savefig(output/(stem+'.pdf'),facecolor='white')
        save_chart(fig,company,bars,output/(stem+'-chart.png'))
        plt.close(fig)
    info=narrative(company)
    (output/(stem+'.txt')).write_text(info['text'],encoding='utf-8')
    return {'png':output/(stem+'.png'),'chart':output/(stem+'-chart.png'),'pdf':output/(stem+'.pdf'),'text':info['text']}


def render_top(repository,output):
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    report=repository.report; stem='top10-'+report['as_of']; analyses=[]
    with RENDER_LOCK:
        with PdfPages(output/(stem+'.pdf')) as pdf:
            fig=summary_figure(report); fig.savefig(output/(stem+'.png'),dpi=160); pdf.savefig(fig); plt.close(fig)
            for company in report['top10']:
                bars=repository.bars(company['ticker']); fig=figure(company,bars)
                pdf.savefig(fig)
                chart=output/f"{company['ticker']}-{company['as_of']}-chart.png"
                save_chart(fig,company,bars,chart); plt.close(fig)
                info=narrative(company)
                analyses.append({'ticker':company['ticker'],'chart':str(chart),'text':info['text'],'label':info['label']})
    text=f"Top 10 | {report['as_of']}\n{report['selected_count']} kandidat lolos; {report['unfilled_slots']} slot belum terisi.\n\n"
    text+='\n\n'.join(f"{c['rank']}. {c['ticker']} - skor {c['score']['total']:.1f}\n{recommendation(c)[1]}" for c in report['top10'])
    text+='\n\nValuasi belum direview. Broker flow ON_HOLD. Gunakan /stock KODE untuk kajian lengkap.'
    (output/(stem+'.txt')).write_text(text,encoding='utf-8')
    return {'png':output/(stem+'.png'),'pdf':output/(stem+'.pdf'),'text':text,'analyses':analyses}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True); parser.add_argument('--prices',required=True)
    parser.add_argument('--output',required=True); parser.add_argument('--ticker')
    args=parser.parse_args(argv); repository=ReportRepository(args.run_dir,args.prices)
    artifacts=render_stock(repository.company(args.ticker),repository.bars(symbol_for(args.ticker)[0]),args.output) if args.ticker else render_top(repository,args.output)
    print(json.dumps({k:str(v) for k,v in artifacts.items() if k not in ('text','analyses')},indent=2))


if __name__=='__main__': main()
