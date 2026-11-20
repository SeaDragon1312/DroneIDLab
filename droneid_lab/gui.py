"""Tk desktop viewer. Worker owns DSP; Tk and matplotlib updates remain on UI thread."""
import json,queue,threading,tkinter as tk
from tkinter import ttk,filedialog,messagebox
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from .pipeline import Config,decode_file,export,summary,safe_payload,valid_positions,FIELD_SCHEMA,Cancelled,confirmed

def status_label(result):
    if result['status']=='crc_pass':return 'Đạt kiểm tra CRC'
    if result['status']=='crc_fail':return 'CRC trượt — chưa hợp lệ'
    if result['status']=='parse_failed':return 'Lỗi parse payload'
    if result['status']=='error':
        stage=result['error_stage']
        return 'Lỗi Turbo' if stage=='turbo' else f'Lỗi giải điều chế: {stage}'
    return result['status']

def crc_label(value):
    return 'PASS' if value is True else 'FAIL' if value is False else 'Chưa xác định'

class App:
    def __init__(self,root):
        self.root=root;root.title('DroneID');root.geometry('1280x900')
        self.events=queue.Queue();self.cancel=threading.Event();self.results=[];self.config=Config(mode='turbo');self.busy=False
        self.input_widgets=[]
        controls=ttk.Frame(root,padding=8);controls.pack(fill='x')
        self.path=tk.StringVar();path_entry=ttk.Entry(controls,textvariable=self.path,width=72)
        path_entry.grid(row=0,column=0,columnspan=6,sticky='ew')
        choose_button=ttk.Button(controls,text='Chọn IQ',command=self.choose);choose_button.grid(row=0,column=6)
        self.input_widgets.extend([(path_entry,'normal'),(choose_button,'normal')])
        self.values={}
        fields=[('format','float32',['float32','int16']),('Fs Hz','50000000',None),('Fc Hz (unknown)','',None),('I/Q','IQ',['IQ','QI']),('byte order','little',['little','big']),('mode','turbo',['turbo','baseline'])]
        for col,(name,value,options) in enumerate(fields):
            ttk.Label(controls,text=name).grid(row=1,column=col)
            var=tk.StringVar(value=value);self.values[name]=var
            widget=ttk.Combobox(controls,textvariable=var,values=options,state='readonly',width=16) if options else ttk.Entry(controls,textvariable=var,width=18)
            widget.grid(row=2,column=col)
            self.input_widgets.append((widget,'readonly' if options else 'normal'))
        self.runbutton=ttk.Button(controls,text='Chạy',command=self.start);self.runbutton.grid(row=3,column=0)
        ttk.Button(controls,text='Hủy',command=self.cancel.set).grid(row=3,column=1)
        self.redact=tk.BooleanVar(value=True)
        ttk.Checkbutton(controls,text='Che định danh/vị trí',variable=self.redact,command=self.refresh).grid(row=3,column=2,columnspan=2)
        self.exportbutton=ttk.Button(controls,text='Xuất JSON/CSV',command=self.save);self.exportbutton.grid(row=3,column=4)
        self.progress=ttk.Progressbar(controls,maximum=100);self.progress.grid(row=3,column=5,columnspan=2,sticky='ew')
        self.status=tk.StringVar(value='Chọn IQ. baseline: systematic; turbo: TurboFEC + CRC24 và CRC16.');ttk.Label(root,textvariable=self.status).pack(fill='x')
        ttk.Label(root,text='Fs: mẫu phức/giây; 50000000 = 50 MS/s. Fc bỏ trống nếu không biết. CRC không xác thực người phát.').pack(fill='x')
        ttk.Label(root,text='App chưa được xác minh là pilot; home riêng biệt. Altitude ≠ height. Vận tốc/góc: raw, chưa xác minh đơn vị/yaw.').pack(fill='x')
        self.equalization=tk.StringVar(value='zf')
        eq_controls=ttk.Frame(root);eq_controls.pack(fill='x')
        ttk.Label(eq_controls,text='Cân bằng kênh').pack(side='left')
        eq_selector=ttk.Combobox(eq_controls,textvariable=self.equalization,values=['zf','none'],state='readonly',width=8)
        eq_selector.pack(side='left');self.input_widgets.append((eq_selector,'readonly'))
        cols=['candidate','slice','status','CRC16','CRC24','serial','drone lat/lon','app lat/lon','home lat/lon','altitude m','height m','vN/vE/vU raw','angle raw']
        frame=ttk.Frame(root);frame.pack(fill='x')
        self.table=ttk.Treeview(frame,columns=cols,show='headings',height=7)
        for name in cols:self.table.heading(name,text=name);self.table.column(name,width=110,stretch=False)
        self.table.pack(fill='x');scroll=ttk.Scrollbar(frame,orient='horizontal',command=self.table.xview);scroll.pack(fill='x');self.table.configure(xscrollcommand=scroll.set)
        self.table.bind('<<TreeviewSelect>>',lambda e:self.select())
        self.detail=tk.Text(root,height=5,wrap='word');self.detail.pack(fill='x')
        self.figure=Figure(figsize=(12,5),layout='constrained');self.axes=self.figure.subplots(2,2)
        self.canvas=FigureCanvasTkAgg(self.figure,master=root);self.canvas.get_tk_widget().pack(fill='both',expand=True)
        root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
    def choose(self):
        path=filedialog.askopenfilename(title='Chọn file IQ offline')
        if path:self.path.set(path)
    def start(self):
        if self.busy:return
        try:
            v={k:x.get() for k,x in self.values.items()}
            try:
                fs=float(v['Fs Hz']);fc=float(v['Fc Hz (unknown)']) if v['Fc Hz (unknown)'].strip() else None
            except ValueError:raise ValueError('Fs và Fc phải là số theo Hz; ví dụ Fs = 50000000. Fc có thể để trống.')
            self.config=Config(fs=fs,fc=fc,format=v['format'],byte_order=v['byte order'],iq_order=v['I/Q'],mode=v['mode'],equalization=self.equalization.get());self.config.validate()
            path=self.path.get()
            if not path:raise ValueError('Chọn file IQ trước.')
        except Exception as e:
            self.status.set(str(e));messagebox.showerror('Cấu hình',str(e));return
        self.cancel.clear();self.results=[];self.refresh();self.busy=True;self.runbutton.state(['disabled']);self.progress['value']=0
        self.exportbutton.state(['disabled'])
        for widget,_ in self.input_widgets:widget.configure(state='disabled')
        self.status.set('Đang giải mã; hủy được kiểm tra giữa các ứng viên/khối.')
        def worker():
            try:
                decode_file(path,self.config,self.cancel,lambda p,r:self.events.put(('progress',p,r)))
                self.events.put(('done',None,None))
            except Cancelled:self.events.put(('cancelled',None,None))
            except Exception as e:self.events.put(('error',f'{type(e).__name__}: {e}',None))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,a,b=self.events.get_nowait()
                if kind=='progress':
                    self.progress['value']=a*100
                    if b is not None:
                        self.results.append(b);self.refresh()
                        self.status.set(f'Đã xử lý {len(self.results)} ứng viên; hủy được kiểm tra giữa các khối.')
                else:
                    self.busy=False;self.runbutton.state(['!disabled'])
                    self.exportbutton.state(['!disabled'])
                    for widget,state in self.input_widgets:widget.configure(state=state)
                    s=summary(self.results)
                    message=f"Xong: {s['candidates']} ứng viên; {s['parsed']} parse; {sum(confirmed(r) for r in self.results)} đạt đủ CRC; {s['errors']} lỗi."
                    if kind=='done' and not self.results:message='Không tìm thấy burst phù hợp. Kiểm tra Fs, định dạng và nội dung IQ.'
                    if kind=='cancelled':message='Đã hủy; kết quả đang có chỉ là một phần file.'
                    if kind=='error':message='Không thể giải mã: '+a
                    self.status.set(message)
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def refresh(self):
        selection=self.table.selection();self.table.delete(*self.table.get_children())
        for r in self.results:
            p=safe_payload(r['payload'],self.redact.get()) if confirmed(r) else {}
            pair=lambda a,b:f"{p[a]}, {p[b]}" if a in p and b in p else ''
            self.table.insert('', 'end',iid=str(r['candidate']),values=[r['candidate'],f"[{r['start']},{r['end']})",status_label(r),crc_label(r['crc16']),crc_label(r['crc24']),p.get('serial_number',''),pair('latitude','longitude'),pair('app_lat','app_lon'),pair('latitude_home','longitude_home'),p.get('altitude',''),p.get('height',''),'/'.join(str(p[k]) for k in ['v_north','v_east','v_up'] if k in p),p.get('d_1_angle','')])
        if selection and self.table.exists(selection[0]):self.table.selection_set(selection);self.select()
        elif self.results:self.table.selection_set(str(self.results[0]['candidate']));self.select()
        else:
            self.detail.delete('1.0','end')
            for ax in self.axes.flat:ax.clear()
            self.canvas.draw_idle()
    def select(self):
        selected=self.table.selection()
        if not selected:return
        r=next(r for r in self.results if str(r['candidate'])==selected[0]);inter=r['intermediates']
        self.detail.delete('1.0','end')
        display={'trạng thái':status_label(r),'decoder_mode':r.get('decoder_mode'),'crc24':r['crc24'],'confirmed':confirmed(r),'fec':r.get('fec_info'),'status':r['status'],'error_stage':r['error_stage'],'error':r['error'],'attempts':r['attempts'],'payload':safe_payload(r['payload'],self.redact.get()) if confirmed(r) else {},'units':FIELD_SCHEMA}
        self.detail.insert('1.0',json.dumps(display,ensure_ascii=False))
        for ax in self.axes.flat:ax.clear()
        a,b,c,d=self.axes.flat
        if 'raw_cut' in inter:
            iq=inter['raw_cut'];a.plot(np.arange(len(iq))/r['Fs_Hz']*1e6,np.abs(iq)**2,lw=.6)
            a.set(title=f"Raw cut trước CFO, N={len(iq)}, Fs={r['Fs_Hz']/1e6:g} MS/s",xlabel='µs từ đầu cut',ylabel='|IQ|² a.u.²')
            n=1<<(len(iq)-1).bit_length();s=np.abs(np.fft.fftshift(np.fft.fft(iq*np.hanning(len(iq)),n)))
            f=np.fft.fftshift(np.fft.fftfreq(n,1/r['Fs_Hz']))
            b.plot((f+(self.config.fc or 0))/1e6,20*np.log10(np.maximum(s/s.max(),1e-12)),lw=.6)
            b.set(title=f'Raw cut spectrum Hann, FFT={n}',xlabel='RF MHz (Fc người dùng)' if self.config.fc else 'Baseband MHz; Fc unknown',ylabel='dB tương đối peak',ylim=(-100,5))
        if 'symbols' in inter:
            q=inter['symbols']['qpsk_input'];c.scatter(q.real.ravel(),q.imag.ravel(),s=2,alpha=.3)
            c.set(title=f'Đầu vào QPSK; {self.config.mode}; EQ={self.config.equalization}; {q.shape}; FFT1024; Fs15.36 MS/s',xlabel='I a.u.',ylabel='Q a.u.')
        d.set(title='Đồ thị kinh/vĩ độ offline — không có bản đồ nền',xlabel='Longitude [degree]',ylabel='Latitude [degree]')
        positions=valid_positions(r)
        if self.redact.get():d.text(.1,.5,'Vị trí đang được che',transform=d.transAxes)
        elif not positions:d.text(.1,.5,'Không có vị trí hợp lệ + CRC pass',transform=d.transAxes)
        else:
            for name,(lat,lon) in positions.items():d.scatter([lon],[lat],label=name)
            d.legend();d.ticklabel_format(useOffset=False,style='plain')
        self.canvas.draw_idle()
    def save(self):
        if self.busy:return
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json'),('CSV','*.csv')])
        if path:
            try:
                export(path,self.results,self.config,self.redact.get())
                self.status.set('Đã xuất '+('JSON.' if path.lower().endswith('.json') else 'CSV và file .metadata.json đi kèm.'))
            except Exception as e:messagebox.showerror('Xuất',str(e))
    def close(self):self.cancel.set();self.root.destroy()

def main():
    root=tk.Tk();App(root);root.mainloop()
