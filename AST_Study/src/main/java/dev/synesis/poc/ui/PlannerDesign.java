package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.time.*;
import java.time.format.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.*;

/** Figma's six planner screens, backed by the portable user-data store. */
public final class PlannerDesign extends JPanel implements Scrollable {
    final PlannerWeekView weeklyView;
    final PlannerMonthView monthlyView;
    final PlannerStore store;final Clock clock;State state=State.empty();LocalDate anchor;boolean monthly,readFailed;
    final JButton add,previous,next,today,week,month,bell,goalButton,addTask,previousTaskDay,nextTaskDay;
    final JLabel range=heading("",18),status=label("",12,ERROR_COLOR),taskHeading=heading("",18),taskCount=label("",12,MUTED);
    final JPanel calendar=new JPanel(new BorderLayout());final Card tasks=new Card(Color.WHITE,12),upcoming=new Card(Color.WHITE,12);
    final JPanel taskRows=new Rows(),upcomingRows=new Rows();final javax.swing.Timer refreshTimer;LocalDate lastToday,taskDate;double weeklyScrollMinute=7*60;
    private SwingWorker<State,Void> pendingRefresh;
    private boolean refreshAgain,disposed;
    private long viewRevision;
    private StoreStamp loadedStamp;
    private Window attachedWindow;
    private final WindowAdapter refreshActivity=new WindowAdapter(){
        @Override public void windowActivated(WindowEvent e){updateRefreshActivity();}
        @Override public void windowDeactivated(WindowEvent e){updateRefreshActivity();}
        @Override public void windowIconified(WindowEvent e){updateRefreshActivity();}
        @Override public void windowDeiconified(WindowEvent e){updateRefreshActivity();}
    };
    private record StoreStamp(boolean exists,long size,java.nio.file.attribute.FileTime modified,Object key){}
    private StoreStamp storeStamp()throws java.io.IOException{
        try{BasicFileAttributes a=Files.readAttributes(store.file(),BasicFileAttributes.class);return new StoreStamp(true,a.size(),a.lastModifiedTime(),a.fileKey());}
        catch(NoSuchFileException e){return new StoreStamp(false,0,null,null);}
    }
    private List<Event> calendarEvents;
    private List<Tag> calendarTags;
    private LocalDate calendarAnchor,calendarToday;
    private boolean calendarMonthly;
    private ViewData renderedView;
    private record ViewData(LocalDate anchor,LocalDate taskDate,LocalDate today,boolean monthly,boolean readFailed,
                            List<Event> events,List<Tag> tags,List<Task> tasks,List<Goal> goals,
                            List<WeeklyTask> weeklyTasks,List<Tag> todoTags,List<WeeklyGoal> weeklyGoals,List<MonthlyTask> monthlyTasks){}

    public PlannerDesign(){this(new PlannerStore(),Clock.systemDefaultZone());}
    public PlannerDesign(PlannerStore store,Clock clock){
        super(null);this.store=store;this.clock=clock;anchor=LocalDate.now(clock);lastToday=anchor;taskDate=anchor;
        setBackground(Color.WHITE);setPreferredSize(new Dimension(1430,824));setMinimumSize(new Dimension(320,400));name(this,"플래너");
        add=button("+ 일정 추가",true,()->editEvent(null,anchor.atTime(10,0)));add.setFont(medium(14));
        previous=PlannerWeekView.navigationButton("‹","이전 달",true,()->navigate(-1));next=PlannerWeekView.navigationButton("›","다음 달",true,()->navigate(1));
        today=PlannerWeekView.navigationButton("오늘","이번 달로 이동",false,this::goToday);week=button("주간",false,()->setMonthly(false));month=button("월간",true,()->setMonthly(true));
        bell=iconButton("bell","알림 · 추후 지원",40,()->{});bell.setEnabled(false);bell.setToolTipText("알림은 추후 지원할 예정이에요.");
        goalButton=new JButton(){@Override protected void paintComponent(Graphics graphics){
            Graphics2D g=quality(graphics);int width=getWidth();boolean compact=width<900;Goal goal=goal();g.setColor(SURFACE);g.fillRoundRect(0,0,width,getHeight(),16,16);
            int left=width<560?44:60;icon("goal-check",width<560?20:24).paintIcon(this,g,width<560?12:16,20);
            int textWidth=compact?width-left-80:width-500;
            drawText(g,(monthly?"이번 달 목표 · ":"이번 주 목표 · ")+(goal==null?"목표를 설정해 보세요":goal.title()),medium(width<560?12:14),NAVY,left,compact?6:11,textWidth);
            drawText(g,goal==null?"목표와 진행 상황을 직접 기록할 수 있어요.":goal.completed()+"개 완료했어요. 학습 흐름을 이어가 보세요.",regular(width<560?10:12),MUTED,left,compact?27:33,compact?width-left-12:width-500);
            int progress=compact?width-left-16:Math.min(300,Math.max(80,width-800)),x=compact?left:width-116-progress,y=compact?51:28;
            g.setColor(BORDER);g.fillRoundRect(x,y,progress,compact?6:8,8,8);if(goal!=null){g.setColor(NAVY);g.fillRoundRect(x,y,(int)(progress*goal.completed()/(double)goal.target()),compact?6:8,8,8);}
            drawText(g,goal==null?"—":goal.completed()+" / "+goal.target(),medium(width<560?12:14),NAVY,width-(compact?72:96),compact?7:21,compact?64:88);g.dispose();
        }};
        goalButton.setUI(new javax.swing.plaf.basic.BasicButtonUI());goalButton.setBorder(null);goalButton.setContentAreaFilled(false);goalButton.addActionListener(e->editGoal());name(goalButton,"목표 설정 및 진행 수정");
        for(Component c:List.of(add,previous,next,today,week,month,bell,range,status,calendar,tasks,upcoming,goalButton))add(c);
        status.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));status.addMouseListener(new MouseAdapter(){public void mouseClicked(MouseEvent e){reload();}});
        calendar.setOpaque(false);tasks.setLayout(null);upcoming.setLayout(null);taskRows.setLayout(new BoxLayout(taskRows,BoxLayout.Y_AXIS));taskRows.setBackground(Color.WHITE);upcomingRows.setLayout(new BoxLayout(upcomingRows,BoxLayout.Y_AXIS));upcomingRows.setBackground(Color.WHITE);
        put(tasks,taskHeading,20,20,308,28);put(tasks,taskCount,20,60,308,20);put(tasks,scroll(taskRows),20,92,308,162);
        addTask=button("+ 할 일 추가",false,()->editTask(null));addTask.setFont(medium(14));put(tasks,addTask,20,260,308,36);
        previousTaskDay=iconButton("previous","이전 날짜의 할 일",14,()->navigateTasks(-1));nextTaskDay=iconButton("next","다음 날짜의 할 일",14,()->navigateTasks(1));tasks.add(previousTaskDay);tasks.add(nextTaskDay);
        put(upcoming,heading("다가오는 일정",18),20,20,308,28);put(upcoming,scroll(upcomingRows),20,60,308,102);
        weeklyView=new PlannerWeekView(this);add(weeklyView);
        monthlyView=new PlannerMonthView(this);add(monthlyView);
        refreshTimer=new javax.swing.Timer(15000,e->refreshFromStore(false));reload();
        addHierarchyListener(e->{if((e.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0)updateRefreshActivity();});
    }
    void goToday(){LocalDate now=LocalDate.now(clock);anchor=now;if(monthly)monthlyView.selectDate(now);else refresh();}
    void setMonthly(boolean value){monthly=value;refresh();}
    void navigate(int amount){try{LocalDate next=monthly?anchor.plusMonths(amount):anchor.plusWeeks(amount);if(next.getYear()<1900||next.getYear()>2200)throw new DateTimeException("range");anchor=next;if(monthly){monthlyView.selectedDate=anchor;taskDate=anchor;}refresh();}catch(DateTimeException e){status.setText("이동할 수 있는 날짜를 벗어났어요.");}}
    void navigateTasks(int days){try{taskDate=taskDate.plusDays(days);if(monthly)monthlyView.refreshDaily();else weeklyView.refreshDaily();}catch(DateTimeException ignored){}}
    void reload(){viewRevision++;try{state=store.load();readFailed=false;status.setText("");refresh();}catch(Exception e){readFailed=true;status.setText(e.getMessage()+" · 클릭해서 다시 읽기");status.setToolTipText(status.getText());writeEnabled(false);}}
    void writeEnabled(boolean enabled){add.setEnabled(enabled);addTask.setEnabled(enabled);goalButton.setEnabled(enabled);if(weeklyView!=null)weeklyView.writeEnabled(enabled);if(monthlyView!=null)monthlyView.writeEnabled(enabled);}
    void accept(State value){viewRevision++;state=value;readFailed=false;status.setText("");refresh();}
    interface Save {State run() throws java.io.IOException;}
    void save(Save write){try{accept(write.run());}catch(Exception e){status.setText(e.getMessage());status.setToolTipText(e.getMessage());}}
    void refresh(){
        // A receipt/revision change need not recreate visible components. Restore write controls even after a failed read.
        writeEnabled(!readFailed);LocalDate current=LocalDate.now(clock);
        ViewData data=new ViewData(anchor,taskDate,current,monthly,readFailed,state.events(),state.tags(),state.tasks(),state.goals(),state.weeklyTasks(),state.todoTags(),state.weeklyGoals(),state.monthlyTasks());
        if(data.equals(renderedView))return;
        ScrollCacheViewport.invalidateContent(this);
        ViewData previousView=renderedView;renderedView=data;
        boolean modeChanged=previousView==null||previousView.monthly()!=monthly;
        LocalDate start=weekStart(anchor),end=start.plusDays(6);
        range.setText(monthly?anchor.format(DateTimeFormatter.ofPattern("uuuu년 M월")):start.format(DateTimeFormatter.ofPattern("uuuu년 M월 d일"))+" — "+(start.getMonth().equals(end.getMonth())?end.getDayOfMonth()+"일":end.format(DateTimeFormatter.ofPattern("M월 d일"))));
        week.setBackground(monthly?Color.WHITE:NAVY);week.setForeground(monthly?NAVY:Color.WHITE);month.setBackground(monthly?NAVY:Color.WHITE);month.setForeground(monthly?Color.WHITE:NAVY);
        if(calendar.getComponentCount()==0||calendarMonthly!=monthly||!Objects.equals(calendarAnchor,anchor)
                ||!Objects.equals(calendarToday,LocalDate.now(clock))||!Objects.equals(calendarEvents,state.events())
                ||!Objects.equals(calendarTags,state.tags())){
            calendarEvents=state.events();calendarTags=state.tags();calendarAnchor=anchor;
            calendarToday=LocalDate.now(clock);calendarMonthly=monthly;
            calendar.removeAll();calendar.add(new PlannerCalendar(this));calendar.revalidate();calendar.repaint();
        }
        if(monthly)monthlyView.refresh();else weeklyView.refresh();
        if(modeChanged){for(Component child:getComponents())child.setVisible(monthly?child==monthlyView:child==weeklyView);revalidate();repaint();}
    }
    @Override public void doLayout(){JPanel view=monthly?monthlyView:weeklyView;view.setBounds(0,0,getWidth(),getHeight());view.doLayout();}
    void editEvent(Event event,LocalDateTime seed){if(readFailed)return;showDialog(this,new EventEditor(store,state,event,seed,this::accept,clock),event==null?"일정 추가":"일정 수정",920,804);}
    JButton eventButton(Occurrence o,boolean compact){return monthly?PlannerMonthView.eventButton(o,!compact,()->editEvent(o.event(),o.start())):PlannerWeekView.eventButton(o,compact,state,()->editEvent(o.event(),o.event().start()));}
    static Color surface(Color c){if(c.getRGB()==NAVY.getRGB())return SURFACE;return new Color((int)(c.getRed()*.06+255*.94),(int)(c.getGreen()*.06+255*.94),(int)(c.getBlue()*.06+255*.94));}
    void dayEvents(LocalDate date){showDialog(this,dayEventsPanel(date),"하루 일정",480,420);}
    JPanel dayEventsPanel(LocalDate date){
        JPanel p=new ModalPanel(new BorderLayout(12,16));p.putClientProperty("planner.backdropDismiss",true);
        p.setBackground(Color.WHITE);p.setBorder(BorderFactory.createEmptyBorder(24,24,24,24));
        p.add(heading(date.format(DateTimeFormatter.ofPattern("M월 d일 EEEE",Locale.KOREAN)),20),BorderLayout.NORTH);
        JPanel rows=new JPanel();rows.setLayout(new BoxLayout(rows,BoxLayout.Y_AXIS));rows.setBackground(Color.WHITE);
        for(Occurrence o:occurrences(state,date,date.plusDays(1))){
            JButton b=button((o.event().allDay()?"종일":o.start().format(DateTimeFormatter.ofPattern("HH:mm")))+" · "+o.event().title(),false,()->{close(p);SwingUtilities.invokeLater(()->editEvent(o.event(),o.start()));});
            b.setMaximumSize(new Dimension(Integer.MAX_VALUE,40));rows.add(b);rows.add(Box.createVerticalStrut(8));
        }
        for(Task task:state.tasks().stream().filter(t->t.date().equals(date)).toList()){
            JButton b=button((task.completed()?"완료 · ":"할 일 · ")+task.title(),false,()->{close(p);SwingUtilities.invokeLater(()->editTask(task));});
            b.setMaximumSize(new Dimension(Integer.MAX_VALUE,40));rows.add(b);rows.add(Box.createVerticalStrut(8));
        }
        if(rows.getComponentCount()==0)rows.add(label("등록한 일정과 할 일이 없어요.",14,BLUE_MUTED));p.add(scroll(rows));
        JPanel actions=actions();JButton dismiss=button("닫기",false,()->requestClose(p));actions.add(dismiss);p.putClientProperty("planner.defaultButton",dismiss);
        actions.add(button("+ 일정 추가",true,()->{close(p);SwingUtilities.invokeLater(()->editEvent(null,date.atTime(10,0)));}));p.add(actions,BorderLayout.SOUTH);return p;
    }
    void renderTasks(){monthlyView.refreshDaily();}
    void renderUpcoming(){monthlyView.renderUpcoming();}
    Goal goal(){return state.goals().stream().filter(g->g.period().equals(period(anchor,monthly))).findFirst().orElse(null);}
    static JPanel actions(){JPanel p=new JPanel(new FlowLayout(FlowLayout.RIGHT,12,0));p.setOpaque(false);return p;}
    static JPanel smallForm(String title){JPanel p=new JPanel(new BorderLayout(12,16));p.setBackground(Color.WHITE);p.setBorder(BorderFactory.createEmptyBorder(24,24,24,24));p.add(heading(title,20),BorderLayout.NORTH);return p;}
    void editTask(Task old){if(readFailed)return;showDialog(this,new PlannerWeekEditors.Daily(this,old),old==null?"오늘의 TODO 생성":"오늘의 TODO 편집",480,470);}
    void editGoal(){Goal old=goal();String period=period(anchor,monthly);JPanel p=smallForm(monthly?"이번 달 목표":"이번 주 목표"),form=new JPanel(new GridLayout(0,1,0,8));form.setOpaque(false);JTextField title=field("목표 이름",old==null?"":old.title());JSpinner target=new JSpinner(new SpinnerNumberModel(old==null?3:old.target(),1,100000,1)),completed=new JSpinner(new SpinnerNumberModel(old==null?0:old.completed(),0,100000,1));target.setFont(regular(14));completed.setFont(regular(14));name(target,"목표 개수");name(completed,"완료 개수");form.add(label("목표 *",12,INK));form.add(title);form.add(label("목표 개수",12,INK));form.add(target);form.add(label("완료 개수",12,INK));form.add(completed);JLabel error=label("",12,ERROR_COLOR);form.add(error);p.add(form);JPanel actions=actions();actions.add(button("취소",false,()->close(p)));actions.add(button("저장",true,()->{try{target.commitEdit();completed.commitEdit();accept(store.saveGoal(new Goal(period,title.getText(),(int)target.getValue(),(int)completed.getValue())));close(p);}catch(Exception e){error.setText(e.getMessage());}}));p.add(actions,BorderLayout.SOUTH);showDialog(this,p,"목표 설정",480,440);}
    @Override public void addNotify(){super.addNotify();attachedWindow=SwingUtilities.getWindowAncestor(this);if(attachedWindow!=null)attachedWindow.addWindowListener(refreshActivity);updateRefreshActivity();}
    @Override public void removeNotify(){refreshTimer.stop();if(attachedWindow!=null)attachedWindow.removeWindowListener(refreshActivity);attachedWindow=null;super.removeNotify();}
    private void updateRefreshActivity(){
        if(!disposed&&isShowing()&&(attachedWindow==null||attachedWindow.isActive())){refreshTimer.start();refreshFromStore();}else refreshTimer.stop();
    }
    public void refreshFromStore(){refreshFromStore(true);}
    private void refreshFromStore(boolean force){
        if(!SwingUtilities.isEventDispatchThread()){SwingUtilities.invokeLater(()->refreshFromStore(force));return;}
        if(disposed||!isShowing())return;
        if(!LocalDate.now(clock).equals(lastToday)){if(taskDate.equals(lastToday))taskDate=LocalDate.now(clock);lastToday=LocalDate.now(clock);refresh();}
        if(pendingRefresh!=null){refreshAgain|=force;return;}
        long before=viewRevision;StoreStamp knownStamp=loadedStamp;boolean mustRead=force||readFailed;
        pendingRefresh=new SwingWorker<>(){
            private StoreStamp stamp;
            @Override protected PlannerModel.State doInBackground()throws Exception{
                StoreStamp current=storeStamp();
                if(!mustRead&&current.equals(knownStamp))return null;
                PlannerModel.State result=store.load();StoreStamp after=storeStamp();
                // A concurrent atomic replacement must be read again next time.
                stamp=current.equals(after)?after:null;return result;
            }
            @Override protected void done(){
                if(pendingRefresh!=this)return;pendingRefresh=null;
                if(disposed)return;
                try{
                    PlannerModel.State latest=get();
                    if(viewRevision==before){if(latest!=null){if(readFailed||latest.revision()!=state.revision())accept(latest);loadedStamp=stamp;}}
                    else refreshAgain=true; // Never replace an edit with an older in-flight read.
                }catch(Exception e){if(viewRevision==before){readFailed=true;writeEnabled(false);Throwable cause=e.getCause()==null?e:e.getCause();status.setText("플래너를 읽지 못했어요. 클릭해서 다시 읽기 · "+cause.getMessage());}}
                boolean again=refreshAgain;refreshAgain=false;if(again)refreshFromStore();
            }
        };pendingRefresh.execute();
    }
    public void dispose(){disposed=true;refreshTimer.stop();if(attachedWindow!=null)attachedWindow.removeWindowListener(refreshActivity);if(pendingRefresh!=null){pendingRefresh.cancel(false);pendingRefresh=null;}}
    final class Rows extends JPanel implements Scrollable {
        @Override public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
        @Override public int getScrollableUnitIncrement(Rectangle r,int o,int d){return 24;}
        @Override public int getScrollableBlockIncrement(Rectangle r,int o,int d){return Math.max(24,r.height-24);}
        @Override public boolean getScrollableTracksViewportWidth(){return true;}
        @Override public boolean getScrollableTracksViewportHeight(){return false;}

    }
    private int viewportWidth(){return getParent() instanceof JViewport v?v.getWidth():getWidth()>0?getWidth():1430;}
    private int minimumHeight(int width){return monthly&&monthlyView!=null?monthlyView.minimumHeight(width):weeklyView==null?824:weeklyView.minimumHeight(width);}
    @Override public Dimension getPreferredSize(){return new Dimension(monthly?1550:1430,minimumHeight(viewportWidth()));}
    @Override public Dimension getPreferredScrollableViewportSize(){return getPreferredSize();}
    @Override public int getScrollableUnitIncrement(Rectangle r,int o,int d){return 24;}
    @Override public int getScrollableBlockIncrement(Rectangle r,int o,int d){return o==SwingConstants.VERTICAL?r.height-24:r.width-24;}
    @Override public boolean getScrollableTracksViewportWidth(){return true;}
    @Override public boolean getScrollableTracksViewportHeight(){return getParent() instanceof JViewport v&&v.getHeight()>=minimumHeight(v.getWidth());}
}
