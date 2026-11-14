package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.swing.*;
import javax.swing.event.*;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.time.format.*;
import java.util.*;
import java.util.List;
import java.util.function.*;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;

/** Native modal editors. Closing or cancelling never commits an unfinished event. */
final class PlannerDialogs {
    private PlannerDialogs() {}
    static void showDialog(Component anchor,JPanel panel,String title,int width,int height){
        JRootPane root=SwingUtilities.getRootPane(anchor);
        if((Boolean.TRUE.equals(panel.getClientProperty("planner.backdropDismiss"))||panel instanceof EventEditor)&&root!=null){new PlannerDayOverlay(root,panel,width,height).showOverlay();return;}
        Window owner=SwingUtilities.getWindowAncestor(anchor);JDialog dialog=new JDialog(owner,title,Dialog.ModalityType.DOCUMENT_MODAL);dialog.setUndecorated(true);
        JRootPane ownerRoot=owner instanceof RootPaneContainer r?r.getRootPane():null;
        try{withDimmedOwner(ownerRoot,()->{
        Runnable close=dialog::dispose;panel.putClientProperty("planner.close",close);
        installDismissal(dialog,panel);dialog.setContentPane(panel);
        Rectangle available=owner==null?GraphicsEnvironment.getLocalGraphicsEnvironment().getMaximumWindowBounds():owner.getGraphicsConfiguration().getBounds();
        int ownerWidth=owner==null?available.width:owner.getWidth(),ownerHeight=owner==null?available.height:owner.getHeight();
        dialog.setSize(Math.min(width,Math.min(available.width-48,Math.max(600,ownerWidth-32))),Math.min(height,Math.min(available.height-80,Math.max(300,ownerHeight-32))));dialog.setLocationRelativeTo(owner);
        if(dialog.getGraphicsConfiguration().getDevice().isWindowTranslucencySupported(GraphicsDevice.WindowTranslucency.PERPIXEL_TRANSPARENT)){
            try{dialog.setShape(new java.awt.geom.RoundRectangle2D.Double(0,0,dialog.getWidth(),dialog.getHeight(),32,32));}catch(UnsupportedOperationException ignored){}
        }
        dialog.setVisible(true);
        });}finally{dialog.dispose();}
    }
    static void installDismissal(JDialog dialog,JPanel panel){
        dialog.setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
        dialog.addWindowListener(new WindowAdapter(){@Override public void windowClosing(WindowEvent e){requestClose(panel);}});
        if(panel.getClientProperty("planner.defaultButton") instanceof JButton button)dialog.getRootPane().setDefaultButton(button);
        dialog.getRootPane().registerKeyboardAction(e->requestClose(panel),KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE,0),JComponent.WHEN_IN_FOCUSED_WINDOW);
    }
    static void showBackdropDialog(Component anchor,JPanel panel,String title,int width,int height){
        JRootPane ownerRoot=SwingUtilities.getRootPane(anchor);Window owner=SwingUtilities.getWindowAncestor(anchor);
        JDialog dialog=new JDialog(owner,title,Dialog.ModalityType.DOCUMENT_MODAL);dialog.setUndecorated(true);
        try{
            panel.putClientProperty("planner.close",(Runnable)dialog::dispose);installDismissal(dialog,panel);
            DialogBackdrop backdrop=new DialogBackdrop(panel,width,height,()->requestClose(panel));
            // The dim area belongs to this modal window, so native modality does not swallow outside clicks.
            // Keep the native window opaque so list animation does not require full-window alpha compositing.
            double scale=ownerRoot.getGraphicsConfiguration()==null?1:ownerRoot.getGraphicsConfiguration().getDefaultTransform().getScaleX();
            backdrop.background=new java.awt.image.BufferedImage(Math.max(1,(int)Math.ceil(ownerRoot.getWidth()*scale)),Math.max(1,(int)Math.ceil(ownerRoot.getHeight()*scale)),java.awt.image.BufferedImage.TYPE_INT_RGB);
            Graphics2D g=backdrop.background.createGraphics();try{g.scale(scale,scale);ownerRoot.printAll(g);}finally{g.dispose();}
            dialog.setContentPane(backdrop);dialog.setBounds(new Rectangle(ownerRoot.getLocationOnScreen(),ownerRoot.getSize()));dialog.setVisible(true);
        }finally{dialog.dispose();}
    }
    static final class DialogBackdrop extends JPanel {
        final JPanel panel;final int width,height;java.awt.image.BufferedImage background;
        DialogBackdrop(JPanel panel,int width,int height,Runnable dismiss){
            super(null);this.panel=panel;this.width=width;this.height=height;setOpaque(false);add(panel);
            addMouseListener(new MouseAdapter(){@Override public void mousePressed(MouseEvent e){if(SwingUtilities.isLeftMouseButton(e))dismiss.run();}});
            // Empty areas inside the form belong to the form, rather than to its backdrop.
            panel.addMouseListener(new MouseAdapter(){});
        }
        @Override public void doLayout(){int w=Math.max(1,Math.min(width,getWidth()-32)),h=Math.max(1,Math.min(height,getHeight()-32));panel.setBounds((getWidth()-w)/2,(getHeight()-h)/2,w,h);}
        @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);if(background!=null)graphics.drawImage(background,0,0,getWidth(),getHeight(),null);graphics.setColor(new Color(0,6,18,64));graphics.fillRect(0,0,getWidth(),getHeight());}
    }
    static void withDimmedOwner(JRootPane root,Runnable show){
        if(root==null){show.run();return;}
        Component oldGlass=root.getGlassPane();boolean oldVisible=oldGlass.isVisible();
        JComponent dim=new JComponent(){@Override protected void paintComponent(Graphics g){g.setColor(new Color(0,6,18,64));g.fillRect(0,0,getWidth(),getHeight());}};
        root.setGlassPane(dim);dim.setVisible(true);
        try{show.run();}finally{if(root.getGlassPane()==dim){root.setGlassPane(oldGlass);oldGlass.setVisible(oldVisible);}}
    }
    static void close(JPanel panel){Object action=panel.getClientProperty("planner.close");if(action instanceof Runnable r)r.run();}
    static void requestClose(JPanel panel){Object action=panel.getClientProperty("planner.dismiss");if(action instanceof Runnable r)r.run();else close(panel);}
    static void changed(javax.swing.text.JTextComponent field,Runnable action){field.getDocument().addDocumentListener(new DocumentListener(){public void insertUpdate(DocumentEvent e){action.run();}public void removeUpdate(DocumentEvent e){action.run();}public void changedUpdate(DocumentEvent e){action.run();}});}
    static JPanel header(String title,String subtitle,Runnable close){
        JLabel h=heading(title,20),s=label(subtitle,12,BLUE_MUTED);JButton x=button("×",false,close);
        JPanel p=new JPanel(null){@Override public void doLayout(){h.setBounds(24,12,getWidth()-96,28);s.setBounds(24,40,getWidth()-96,20);x.setBounds(getWidth()-56,20,32,32);}};
        p.setBackground(Color.WHITE);p.setPreferredSize(new Dimension(920,73));p.setBorder(BorderFactory.createMatteBorder(0,0,1,0,BORDER));p.add(h);p.add(s);p.add(x);return p;}
    static void put(Container panel,Component child,int x,int y,int w,int h){panel.add(child);child.setBounds(x,y,w,h);}
    static void fieldLabel(Container p,String title,int x,int y,int w){JLabel label=label(title,12,INK);label.setFont(medium(12));put(p,label,x,y,w,20);}
    static class ModalPanel extends JPanel {
        ModalPanel(LayoutManager layout){super(layout);setOpaque(false);}
        @Override protected void paintComponent(Graphics graphics){Graphics2D g=quality(graphics);g.setColor(getBackground());g.fillRoundRect(0,0,getWidth(),getHeight(),32,32);g.dispose();}
        @Override public void paint(Graphics graphics){Graphics2D g=quality(graphics);g.clip(new java.awt.geom.RoundRectangle2D.Double(0,0,getWidth(),getHeight(),32,32));super.paint(g);g.dispose();}
    }
    static final class EditorBody extends JPanel implements Scrollable {
        final JPanel form,preview;final Map<Component,Rectangle> original=new LinkedHashMap<>();boolean stacked;
        EditorBody(JPanel form,JPanel preview){super(null);this.form=form;this.preview=preview;setBackground(Color.WHITE);add(form);add(preview);}
        int availableWidth(){return getParent() instanceof JViewport viewport&&viewport.getWidth()>0?viewport.getWidth():getWidth()>0?getWidth():920;}
        @Override public Dimension getPreferredSize(){return new Dimension(1,availableWidth()<880?1232:658);}
        @Override public void doLayout(){
            if(original.isEmpty())for(Component child:form.getComponents())original.put(child,new Rectangle(child.getBounds()));
            int width=getWidth();boolean compact=width<880;int formWidth=compact?width-48:Math.min(568,width-352);
            form.setBounds(24,24,Math.max(1,formWidth),610);double scale=formWidth/568.0;
            for(var entry:original.entrySet()){Rectangle b=entry.getValue();entry.getKey().setBounds((int)Math.round(b.x*scale),b.y,Math.max(1,(int)Math.round(b.width*scale)),b.height);}
            preview.setBounds(compact?(width-280)/2:width-304,compact?658:24,280,550);
            if(stacked!=compact){stacked=compact;revalidate();}
        }
        @Override public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
        @Override public int getScrollableUnitIncrement(Rectangle r,int o,int d){return 24;}
        @Override public int getScrollableBlockIncrement(Rectangle r,int o,int d){return Math.max(24,r.height-24);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}
    }

    static final class DateInput extends JButton {
        private LocalDate date;private Runnable change=()->{};
        private final Supplier<LocalDate> limitedWeek;
        private boolean weekSelection,monthSelection;
        private Supplier<LocalDate> limitedMonth;
        DateInput(String name,LocalDate date){this(name,date,null);}
        DateInput(String name,LocalDate date,Supplier<LocalDate> limitedWeek){this.date=date;this.limitedWeek=limitedWeek;setUI(new javax.swing.plaf.basic.BasicButtonUI());setFont(regular(14));setForeground(INK);setBackground(Color.WHITE);setBorder(inputBorder());setHorizontalAlignment(LEFT);setFocusPainted(false);name(this,name);refresh();addActionListener(e->popup().show(this,0,getHeight()));}
        LocalDate date(){return date;}
        DateInput weeks(){weekSelection=true;date=weekStart(date);refresh();return this;}
        DateInput months(){monthSelection=true;date=date.withDayOfMonth(1);refresh();return this;}
        DateInput withinMonth(Supplier<LocalDate> month){limitedMonth=month;return this;}
        void onChange(Runnable action){change=action;}
        boolean selectable(LocalDate value){return (limitedWeek==null||weekStart(value).equals(weekStart(limitedWeek.get())))&&(limitedMonth==null||YearMonth.from(value).equals(YearMonth.from(limitedMonth.get())));}
        boolean selectableMonth(YearMonth value){if(limitedMonth!=null)return value.equals(YearMonth.from(limitedMonth.get()));if(limitedWeek==null)return true;LocalDate start=weekStart(limitedWeek.get());return !value.atEndOfMonth().isBefore(start)&&!value.atDay(1).isAfter(start.plusDays(6));}
        void setDate(LocalDate value){if(value.getYear()<1900||value.getYear()>2200)throw new IllegalArgumentException("날짜는 1900년부터 2200년까지 입력해 주세요.");if(!selectable(value))throw new IllegalArgumentException(limitedMonth==null?"TODO의 주에 포함된 날짜를 선택해 주세요.":"TODO의 월에 포함된 날짜를 선택해 주세요.");date=monthSelection?value.withDayOfMonth(1):weekSelection?weekStart(value):value;refresh();change.run();}
        private void refresh(){setText(date.format(DateTimeFormatter.ofPattern(monthSelection?"uuuu년 M월":"uuuu.MM.dd (E)",Locale.KOREAN)));}
        private JPopupMenu monthPopup(){
            JPopupMenu pop=new JPopupMenu();JPanel panel=new JPanel(new BorderLayout(6,12));panel.setBackground(Color.WHITE);panel.setBorder(BorderFactory.createEmptyBorder(12,12,12,12));
            JSpinner year=new JSpinner(new SpinnerNumberModel(date.getYear(),1900,2200,1));year.setEditor(new JSpinner.NumberEditor(year,"#"));year.setFont(regular(14));name(year,"TODO 연도");panel.add(year,BorderLayout.NORTH);
            JPanel grid=new JPanel(new GridLayout(4,3,6,6));grid.setOpaque(false);
            for(int m=1;m<=12;m++){final int month=m;JButton b=button(m+"월",m==date.getMonthValue(),()->{try{year.commitEdit();setDate(LocalDate.of((Integer)year.getValue(),month,1));pop.setVisible(false);}catch(java.text.ParseException e){year.requestFocusInWindow();}});b.setPreferredSize(new Dimension(70,32));grid.add(b);}panel.add(grid);pop.add(panel);return pop;
        }
        JPopupMenu popup(){if(monthSelection)return monthPopup();JPopupMenu pop=new JPopupMenu();JPanel p=new JPanel(new BorderLayout(6,8));p.setBackground(Color.WHITE);p.setBorder(BorderFactory.createEmptyBorder(12,12,12,12));
            JPanel grid=new JPanel(new GridLayout(0,7,2,2));grid.setBackground(Color.WHITE);JPanel nav=new JPanel(new BorderLayout());nav.setOpaque(false);JLabel month=heading("",14);month.setHorizontalAlignment(SwingConstants.CENTER);YearMonth[] shown={YearMonth.from(date)};
            JButton previous=iconButton("previous","이전 달",16,()->{}),next=iconButton("next","다음 달",16,()->{});
            LocalDate[] hoveredWeek={null};
            Runnable highlightWeek=()->{if(weekSelection)for(Component component:grid.getComponents())if(component instanceof JButton b&&b.getClientProperty("planner.date") instanceof LocalDate day){
                boolean selected=weekStart(day).equals(weekStart(date)),hovered=weekStart(day).equals(hoveredWeek[0]);
                b.setBackground(selected?NAVY:hovered?new Color(0xdce9fa):YearMonth.from(day).equals(shown[0])?new Color(0xf0f7ff):Color.WHITE);
                b.setForeground(selected?Color.WHITE:YearMonth.from(day).equals(shown[0])?NAVY:new Color(0x9caabd));b.repaint();
            }};
            Runnable[] render={null};render[0]=()->{
                hoveredWeek[0]=null;
                grid.removeAll();month.setText(shown[0].format(DateTimeFormatter.ofPattern("uuuu년 M월")));
                for(String d:weekSelection?new String[]{"월","화","수","목","금","토","일"}:new String[]{"일","월","화","수","목","금","토"}){JLabel l=label(d,12,d.equals("토")||d.equals("일")?WEEKEND:MUTED);l.setHorizontalAlignment(SwingConstants.CENTER);grid.add(l);}
                LocalDate first=shown[0].atDay(1).with(java.time.temporal.TemporalAdjusters.previousOrSame(weekSelection?DayOfWeek.MONDAY:DayOfWeek.SUNDAY));
                for(int i=0;i<42;i++){
                    LocalDate day=first.plusDays(i);boolean allowed=selectable(day),selected=allowed&&(weekSelection?weekStart(day).equals(weekStart(date)):day.equals(date)),current=YearMonth.from(day).equals(shown[0]);
                    JButton b=button(Integer.toString(day.getDayOfMonth()),selected,()->{setDate(day);pop.setVisible(false);});b.setPreferredSize(new Dimension(34,30));
                    b.putClientProperty("planner.date",day);b.setEnabled(allowed);
                    if(weekSelection)b.addMouseListener(new MouseAdapter(){
                        @Override public void mouseEntered(MouseEvent e){hoveredWeek[0]=weekStart(day);highlightWeek.run();}
                        @Override public void mouseExited(MouseEvent e){hoveredWeek[0]=null;highlightWeek.run();}
                    });
                    if(!selected){if(limitedWeek!=null){b.setBackground(allowed?new Color(0xf0f7ff):new Color(0xf2f2f2));b.setForeground(allowed?INK:new Color(0xa6a6a6));}else if(current)b.setBackground(new Color(0xf0f7ff));else b.setForeground(new Color(0x9caabd));}
                    grid.add(b);
                }
                highlightWeek.run();
                previous.setEnabled(selectableMonth(shown[0].minusMonths(1)));next.setEnabled(selectableMonth(shown[0].plusMonths(1)));
                p.revalidate();p.repaint();
            };
            previous.addActionListener(e->{shown[0]=shown[0].minusMonths(1);render[0].run();});next.addActionListener(e->{shown[0]=shown[0].plusMonths(1);render[0].run();});
            nav.add(previous,BorderLayout.WEST);nav.add(month);nav.add(next,BorderLayout.EAST);
            JPanel direct=new JPanel(new BorderLayout(6,0));direct.setOpaque(false);JTextField input=field("날짜 직접 입력",date.toString());input.setToolTipText("YYYY-MM-DD 형식으로 입력해 주세요.");JButton apply=button("적용",false,()->{try{setDate(LocalDate.parse(input.getText().strip()));pop.setVisible(false);}catch(DateTimeException|IllegalArgumentException ex){input.setBorder(BorderFactory.createLineBorder(ERROR_COLOR));input.setToolTipText(limitedWeek==null?"YYYY-MM-DD 형식으로 입력해 주세요.":"TODO의 주에 포함된 날짜를 선택해 주세요.");}});input.addActionListener(e->apply.doClick());direct.add(input);direct.add(apply,BorderLayout.EAST);
            p.add(nav,BorderLayout.NORTH);p.add(grid);p.add(direct,BorderLayout.SOUTH);pop.add(p);render[0].run();return pop;}
    }

    static final class EventEditor extends ModalPanel {
        final PlannerStore store;final Event original;final Consumer<State> saved;final Clock clock;
        final JTextField title;final JTextArea description;final DateInput startDate,endDate;final JComboBox<String> startTime,endTime;
        final JCheckBox allDay=check("종일"),important=check("중요 일정");final JComboBox<Repeat> repeat=combo("반복",Repeat.values());
        final JComboBox<String> reminder=combo("알림",new String[]{"추후 지원"});
        final JLabel error=label("* 필수 입력",12,BLUE_MUTED);
        final JPanel tagChips=new JPanel(new FlowLayout(FlowLayout.LEFT,8,0));final JPanel preview=new Preview();
        final JButton addTag=button("+ 태그 추가",false,this::showTagPopup);
        PlannerPopover tagPopover;
        private JPanel cachedTagPicker;private List<Tag> cachedPickerTags;private Set<String> cachedPickerSelection;
        JPanel discardPrompt;Consumer<JPanel> discardPresenter=prompt->showDialog(this,prompt,"작성 취소 확인",440,192);
        private final EditorInput initialInput;
        private record EditorInput(String title,String description,LocalDate startDate,LocalDate endDate,String startTime,String endTime,boolean allDay,boolean important,EventColor color,Set<String> tags,Object repeat){}
        final Set<String> selected=new LinkedHashSet<>();State state;EventColor color=EventColor.NAVY;final List<JButton> swatches=new ArrayList<>();
        EventEditor(PlannerStore store,State state,Event original,LocalDateTime seed,Consumer<State> saved,Clock clock){
            super(new BorderLayout());this.store=store;this.state=state;this.original=original;this.saved=saved;this.clock=clock;setBackground(Color.WHITE);setPreferredSize(new Dimension(920,804));
            putClientProperty("planner.dismiss",(Runnable)this::requestDiscard);
            title=field("일정 제목",original==null?"":original.title());description=new JTextArea(original==null?"":original.description());description.setFont(regular(14));description.setForeground(INK);description.setLineWrap(true);description.setWrapStyleWord(true);description.setBorder(BorderFactory.createEmptyBorder(8,12,8,12));name(description,"일정 설명");
            LocalDateTime start=original==null?seed:original.start(),end=original==null?seed.plusHours(1):original.end();
            startDate=new DateInput("시작 날짜",start.toLocalDate());endDate=new DateInput("종료 날짜",original!=null&&original.allDay()?end.toLocalDate().minusDays(1):end.toLocalDate());
            String[] times=new String[96];for(int i=0;i<96;i++)times[i]=String.format("%02d:%02d",i/4,i%4*15);
            startTime=combo("시작 시간",times);endTime=combo("종료 시간",times);startTime.setEditable(true);endTime.setEditable(true);
            startTime.setSelectedItem(start.toLocalTime().toString());endTime.setSelectedItem(end.toLocalTime().toString());
            if(original!=null){allDay.setSelected(original.allDay());important.setSelected(original.important());repeat.setSelectedItem(original.repeat());selected.addAll(original.tagIds());color=original.color();}reminder.setEnabled(false);reminder.setToolTipText("알림은 추후 지원할 예정이에요.");
            add(header(original==null?"일정 추가":"일정 수정","수업부터 시험까지, 필요한 일정을 한곳에 기록해요.",()->requestClose(this)),BorderLayout.NORTH);
            JPanel form=new JPanel(null);form.setOpaque(false);EditorBody body=new EditorBody(form,preview);
            fieldLabel(form,"일정 제목 *",0,0,568);put(form,title,0,24,568,40);fieldLabel(form,"일정 설명",0,78,568);JScrollPane descriptionScroll=scroll(description);descriptionScroll.setBorder(inputBorder());description.setBorder(BorderFactory.createEmptyBorder(7,0,7,0));put(form,descriptionScroll,0,102,568,56);
            fieldLabel(form,"일정 시간 · 기간 *",0,172,440);put(form,allDay,448,172,120,24);put(form,label("시작",12,BLUE_MUTED),0,200,278,20);put(form,label("종료",12,BLUE_MUTED),290,200,278,20);
            put(form,startDate,0,224,166,40);put(form,startTime,174,224,104,40);put(form,endDate,290,224,166,40);put(form,endTime,464,224,104,40);
            put(form,label("여러 날 이어지는 일정은 종료 날짜를 바꿔주세요.",12,BLUE_MUTED),0,268,568,20);
            fieldLabel(form,"일정 색",0,302,568);
            PlannerColorPicker colors=new PlannerColorPicker(color,value->{color=value;preview.repaint();});
            swatches.addAll(colors.buttons);put(form,colors,0,326,336,40);
            put(form,label("캘린더에 표시할 색상이에요.",12,BLUE_MUTED),352,326,216,32);
            fieldLabel(form,"일정 태그",0,372,480);put(form,button("태그 관리",false,this::tags),488,372,80,24);tagChips.setOpaque(false);put(form,tagChips,0,400,568,32);
            put(form,important,0,446,568,24);put(form,label("체크하면 [다가오는 일정]에 디데이가 표시돼요.",12,BLUE_MUTED),0,474,568,20);
            fieldLabel(form,"반복",0,520,278);fieldLabel(form,"알림",290,520,278);put(form,repeat,0,544,278,36);put(form,reminder,290,544,278,36);
            if(original!=null&&original.repeat()!=Repeat.NONE)put(form,label("반복 일정 전체에 변경사항이 적용돼요.",12,BLUE_MUTED),0,586,568,20);
            add(scroll(body));JPanel footer=new JPanel(new BorderLayout(12,0));footer.setBackground(Color.WHITE);footer.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createMatteBorder(1,0,0,0,BORDER),BorderFactory.createEmptyBorder(16,24,16,24)));footer.setPreferredSize(new Dimension(920,73));
            JPanel actions=new JPanel(new FlowLayout(FlowLayout.RIGHT,12,0));actions.setOpaque(false);if(original!=null){JButton delete=button("삭제",false,()->confirmDelete(this,original.repeat()==Repeat.NONE?"이 일정을 삭제할까요?":"이 반복 일정 전체를 삭제할까요?",()->commit(()->store.deleteEvent(original.id()))));delete.setForeground(ERROR_COLOR);delete.setPreferredSize(new Dimension(64,40));actions.add(delete);}
            JButton cancel=button("취소",false,()->requestClose(this)),save=button(original==null?"일정 추가":"변경사항 저장",true,this::save);cancel.setPreferredSize(new Dimension(112,40));save.setPreferredSize(new Dimension(124,40));actions.add(cancel);actions.add(save);putClientProperty("planner.defaultButton",save);footer.add(error);footer.add(actions,BorderLayout.EAST);add(footer,BorderLayout.SOUTH);
            changed(title,preview::repaint);changed(description,preview::repaint);startDate.onChange(this::syncDates);endDate.onChange(this::syncDates);
            startTime.addActionListener(e->preview.repaint());endTime.addActionListener(e->preview.repaint());important.addActionListener(e->preview.repaint());
            allDay.addActionListener(e->syncTime());syncTime();renderTags();initialInput=inputState();
        }
        private EditorInput inputState(){return new EditorInput(title.getText().isBlank()?"":title.getText(),description.getText().isBlank()?"":description.getText(),startDate.date(),endDate.date(),Objects.toString(startTime.getEditor().getItem(),""),Objects.toString(endTime.getEditor().getItem(),""),allDay.isSelected(),important.isSelected(),color,Set.copyOf(selected),repeat.getSelectedItem());}
        void requestDiscard(){
            hideTagPopup();
            if(discardPrompt!=null)return;
            if(initialInput.equals(inputState())){close(this);return;}
            discardPrompt=new DiscardConfirmation(()->finishDiscard(false),()->finishDiscard(true));
            discardPrompt.putClientProperty("planner.dismiss",(Runnable)()->finishDiscard(false));
            try{discardPresenter.accept(discardPrompt);}catch(RuntimeException error){discardPrompt=null;throw error;}
        }
        void finishDiscard(boolean discard){JPanel prompt=discardPrompt;if(prompt==null)return;discardPrompt=null;close(prompt);if(discard)close(this);}
        void syncDates(){if(endDate.date().isBefore(startDate.date()))endDate.setDate(startDate.date());else preview.repaint();}
        void syncTime(){startTime.setEnabled(!allDay.isSelected());endTime.setEnabled(!allDay.isSelected());preview.repaint();}
        void showTagPopup(){if(tagPopover!=null){hideTagPopup();return;}tagPopover=new PlannerPopover(addTag,tagPicker(),()->tagPopover=null);try{tagPopover.showList();}catch(RuntimeException error){hideTagPopup();throw error;}}
        void hideTagPopup(){if(tagPopover!=null)tagPopover.close();}
        @Override public void removeNotify(){hideTagPopup();super.removeNotify();}
        void renderTags(){hideTagPopup();selected.removeIf(id->state.tags().stream().noneMatch(t->t.id().equals(id)));tagChips.removeAll();for(String id:selected){JButton chip=button(state.tagName(id)+"   ×",false,()->{selected.remove(id);renderTags();});chip.setBackground(SURFACE);chip.setPreferredSize(new Dimension(Math.min(180,chip.getPreferredSize().width),28));tagChips.add(chip);}addTag.setPreferredSize(new Dimension(104,28));tagChips.add(addTag);tagChips.revalidate();tagChips.repaint();preview.repaint();}
        JPanel tagPicker(){
            if(cachedTagPicker!=null&&state.tags().equals(cachedPickerTags)&&selected.equals(cachedPickerSelection))return cachedTagPicker;
            JPanel content=new JPanel(new BorderLayout(0,8));content.setBackground(Color.WHITE);content.setBorder(BorderFactory.createEmptyBorder(12,12,12,12));
            content.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createLineBorder(BORDER),content.getBorder()));name(content,"일정 태그 선택");
            if(state.tags().isEmpty()){
                JLabel empty=label("<html>태그가 없어요.<br>[태그 관리]에서 태그를 생성해주세요.</html>",12,MUTED);
                name(empty,"태그가 없어요. [태그 관리]에서 태그를 생성해주세요.");empty.setPreferredSize(new Dimension(296,48));content.add(empty);
            }else{
                JPanel rows=new JPanel();rows.setLayout(new BoxLayout(rows,BoxLayout.Y_AXIS));rows.setBackground(Color.WHITE);
                for(Tag tag:state.tags()){
                    JCheckBox choice=check(tag.name());choice.setSelected(selected.contains(tag.id()));choice.setToolTipText(tag.name());
                    choice.setPreferredSize(new Dimension(296,32));choice.setMaximumSize(new Dimension(Integer.MAX_VALUE,32));
                    choice.addActionListener(e->{if(choice.isSelected())selected.add(tag.id());else selected.remove(tag.id());renderTags();});rows.add(choice);
                }
                JScrollPane list=scroll(rows);list.setPreferredSize(new Dimension(296,Math.min(240,state.tags().size()*32)));content.add(list);
            }
            JButton manage=button("태그 관리",false,()->{hideTagPopup();SwingUtilities.invokeLater(this::tags);});manage.setPreferredSize(new Dimension(296,32));content.add(manage,BorderLayout.SOUTH);
            cachedPickerTags=state.tags();cachedPickerSelection=Set.copyOf(selected);cachedTagPicker=content;return content;
        }
        void tags(){hideTagPopup();MenuSelectionManager.defaultManager().clearSelectedPath();TagEditor tags=new TagEditor(store,state,selected,(next,ids)->{state=next;selected.clear();selected.addAll(ids);saved.accept(next);renderTags();});showDialog(this,tags,"태그 관리",440,536);}
        Event draft(){LocalTime start=allDay.isSelected()?LocalTime.MIDNIGHT:LocalTime.parse(startTime.getEditor().getItem().toString().strip(),DateTimeFormatter.ofPattern("HH:mm").withResolverStyle(ResolverStyle.STRICT));LocalTime end=allDay.isSelected()?LocalTime.MIDNIGHT:LocalTime.parse(endTime.getEditor().getItem().toString().strip(),DateTimeFormatter.ofPattern("HH:mm").withResolverStyle(ResolverStyle.STRICT));
            return new Event(original==null?PlannerModel.id():original.id(),title.getText(),description.getText(),startDate.date().atTime(start),(allDay.isSelected()?endDate.date().plusDays(1):endDate.date()).atTime(end),allDay.isSelected(),color,new ArrayList<>(selected),important.isSelected(),(Repeat)repeat.getSelectedItem(),original==null?-1:original.reminderMinutes());}
        void save(){try{Event value=draft();commit(()->store.saveEvent(value));}catch(DateTimeException ex){fail("시간은 00:00~23:59로 입력해 주세요.");}catch(IllegalArgumentException ex){fail(ex.getMessage());}}
        interface Write {State run() throws java.io.IOException;}
        void commit(Write write){try{State next=write.run();saved.accept(next);close(this);}catch(Exception ex){fail(ex.getMessage());}}
        void fail(String message){error.setText(message);error.setForeground(ERROR_COLOR);error.setToolTipText(message);}
        final class Preview extends JPanel {
            Preview(){setOpaque(false);}
            @Override protected void paintComponent(Graphics graphics){Graphics2D g=quality(graphics);g.setFont(regular(12));drawCard(g,0,0,280,258,SURFACE);drawText(g,"캘린더 미리보기",medium(14),INK,16,16,248);drawText(g,startDate==null?"":startDate.date().format(DateTimeFormatter.ofPattern("M월 d일 EEEE",Locale.KOREAN)),regular(12),BLUE_MUTED,16,50,248);
                String text=title==null||title.getText().isBlank()?"일정 제목":title.getText();
                String time=allDay.isSelected()?"종일":startTime==null?"":startTime.getEditor().getItem()+"–"+endTime.getEditor().getItem();
                PlannerEventCard.paint(g,16,82,248,132,text,time,new Color(color.rgb),selected.stream().map(state::tagName).filter(name->!name.isBlank()).toList());
                drawCard(g,0,274,280,150,Color.WHITE);drawText(g,"다가오는 일정",medium(14),INK,16,290,248);if(important.isSelected()){drawText(g,text,regular(14),INK,16,332,180);g.setColor(SURFACE);g.fillRoundRect(208,330,56,28,12,12);drawText(g,PlannerModel.dDay(LocalDate.now(clock),startDate.date()),medium(12),NAVY,216,334,44);}else drawText(g,"중요 일정으로 설정하면 표시돼요.",regular(12),BLUE_MUTED,16,334,248);
                drawText(g,"중요 일정의 시작일을 기준으로",regular(12),BLUE_MUTED,16,378,248);drawText(g,"디데이를 표시해요.",regular(12),BLUE_MUTED,16,398,248);drawText(g,"색상은 캘린더 일정에 적용되고,",regular(12),BLUE_MUTED,0,444,280);drawText(g,"태그는 나만의 기준으로 관리할 수 있어요.",regular(12),BLUE_MUTED,0,464,280);g.dispose();}
        }
    }
    static final class DiscardConfirmation extends ModalPanel {
        DiscardConfirmation(Runnable keep,Runnable discard){
            super(new BorderLayout(12,16));setBackground(Color.WHITE);setBorder(BorderFactory.createEmptyBorder(24,24,24,24));
            JPanel text=new JPanel(new GridLayout(0,1,0,6));text.setOpaque(false);text.add(heading("정말 창을 닫을까요?",18));text.add(label("창을 닫으면 작성 중인 내용이 사라져요.",14,MUTED));add(text);
            JPanel actions=new JPanel(new FlowLayout(FlowLayout.RIGHT,12,0));actions.setOpaque(false);
            JButton continueWriting=button("계속 작성",false,keep),close=button("닫기",true,discard);continueWriting.setPreferredSize(new Dimension(112,40));close.setPreferredSize(new Dimension(112,40));actions.add(continueWriting);actions.add(close);add(actions,BorderLayout.SOUTH);
            putClientProperty("planner.defaultButton",continueWriting);
        }
    }
    static final class TagEditor extends ModalPanel {
        final PlannerStore store;final List<Tag> before;final List<Tag> draft;final Set<String> selected;final BiConsumer<State,Set<String>> saved;
        final JPanel rows=new JPanel();final JTextField newName=field("새 태그 이름","");final JLabel error=label("",12,ERROR_COLOR);final Map<String,JTextField> names=new LinkedHashMap<>();
        final boolean todo;
        TagEditor(PlannerStore store,State state,Set<String> selected,BiConsumer<State,Set<String>> saved){this(store,state,selected,saved,false);}
        TagEditor(PlannerStore store,State state,Set<String> selected,BiConsumer<State,Set<String>> saved,boolean todo){super(null);this.todo=todo;this.store=store;this.before=todo?state.todoTags():state.tags();this.draft=new ArrayList<>(before);this.selected=new LinkedHashSet<>(selected);this.saved=saved;setBackground(Color.WHITE);setPreferredSize(new Dimension(440,536));
            put(this,heading("태그 관리",20),24,24,344,28);put(this,label("태그를 선택하고, 이름을 자유롭게 바꿔보세요.",12,BLUE_MUTED),24,52,344,20);put(this,button("×",false,()->close(this)),384,24,32,32);fieldLabel(this,"사용할 태그 · 이름 수정",24,84,392);
            rows.setLayout(new BoxLayout(rows,BoxLayout.Y_AXIS));rows.setBackground(Color.WHITE);put(this,scroll(rows),24,116,392,136);fieldLabel(this,"새 태그 만들기",24,268,392);put(this,newName,24,292,304,40);put(this,button("추가",true,this::create),340,292,76,40);
            put(this,label(todo?"TODO 전용 태그예요. 일정 태그와 별도로 저장해요.":"추가한 태그는 현재 일정에 바로 선택돼요.",12,BLUE_MUTED),24,348,392,20);put(this,error,24,380,392,24);put(this,button("변경사항 저장",true,this::save),24,416,392,40);newName.addActionListener(e->create());render();}
        void capture(){for(int i=0;i<draft.size();i++){Tag t=draft.get(i);if(names.containsKey(t.id()))draft.set(i,new Tag(t.id(),names.get(t.id()).getText()));}}
        void render(){rows.removeAll();names.clear();if(draft.isEmpty()){JLabel l=label("아직 태그가 없어요. 새 태그를 만들어 보세요.",12,BLUE_MUTED);rows.add(l);}for(Tag tag:draft){JPanel row=new JPanel(null);row.setOpaque(false);row.setPreferredSize(new Dimension(392,48));row.setMaximumSize(new Dimension(Integer.MAX_VALUE,48));JCheckBox use=check("");name(use,tag.name()+" 태그 선택");use.setSelected(selected.contains(tag.id()));use.addActionListener(e->{if(use.isSelected())selected.add(tag.id());else selected.remove(tag.id());});put(row,use,0,10,20,20);JTextField rename=field("태그 이름 "+tag.name(),tag.name());names.put(tag.id(),rename);put(row,rename,30,0,286,40);put(row,button("삭제",false,()->{try{capture();draft.removeIf(t->t.id().equals(tag.id()));selected.remove(tag.id());render();}catch(IllegalArgumentException ex){error.setText(ex.getMessage());}}),328,4,64,32);rows.add(row);}rows.revalidate();rows.repaint();}
        void create(){try{capture();Tag tag=new Tag(PlannerModel.id(),newName.getText());if(draft.stream().anyMatch(t->t.name().equalsIgnoreCase(tag.name())))throw new IllegalArgumentException("같은 이름의 태그가 이미 있어요.");draft.add(tag);selected.add(tag.id());newName.setText("");error.setText("");render();}catch(IllegalArgumentException ex){error.setText(ex.getMessage());}}
        void save(){try{capture();State next=todo?store.saveTodoTags(before,draft):store.saveTags(before,draft);selected.removeIf(id->(todo?next.todoTags():next.tags()).stream().noneMatch(t->t.id().equals(id)));saved.accept(next,Set.copyOf(selected));close(this);}catch(Exception ex){error.setText(ex.getMessage());error.setToolTipText(ex.getMessage());}}
    }
    static void confirmDelete(Component anchor,String question,Runnable remove){JPanel p=new JPanel(new BorderLayout(12,16));p.setBackground(Color.WHITE);p.setBorder(BorderFactory.createEmptyBorder(24,24,24,24));p.add(heading(question,16),BorderLayout.NORTH);JPanel actions=new JPanel(new FlowLayout(FlowLayout.RIGHT,12,0));actions.setOpaque(false);actions.add(button("취소",false,()->close(p)));actions.add(button("삭제",true,()->{close(p);remove.run();}));p.add(actions,BorderLayout.SOUTH);showDialog(anchor,p,"삭제 확인",440,160);}
    static void drawCard(Graphics2D g,int x,int y,int w,int h,Color fill){g.setColor(fill);g.fillRoundRect(x,y,w,h,24,24);g.setColor(BORDER);g.drawRoundRect(x,y,w-1,h-1,23,23);}
    static void drawText(Graphics2D g,String text,Font font,Color color,int x,int y,int width){
        if(text==null||text.isEmpty()||width<=0)return;
        int size=font.getSize(),height=size>=28?40:size>=18?28:size>=14?22:size>=12?20:16;
        if(!g.hitClip(x-1,y-1,width+2,height+2))return;
        java.awt.font.TextLayout layout=PlannerTextLayout.get(g,text,font);
        Shape clip=g.getClip();g.clipRect(x,y,width,height);g.setColor(color);
        layout.draw(g,x,y+(height-layout.getAscent()-layout.getDescent())/2+layout.getAscent());g.setClip(clip);
    }
}
