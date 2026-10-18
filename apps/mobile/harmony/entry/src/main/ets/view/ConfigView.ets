@Component
export struct ConfigView {
  @Prop url: string = '';
  @Prop status: string = '';
  @Prop tokenSaved: boolean = false;
  onConnect: (url: string, token: string) => void =
    (url: string, token: string): void => {};
  @State private urlText: string = '';
  @State private tokenText: string = '';

  aboutToAppear(): void {
    this.urlText = this.url;
  }

  build() {
    Column({ space: 12 }) {
      Text('连接 WUXING')
        .fontSize(24)
        .fontWeight(FontWeight.Bold)
        .id('config-title')
      Text('填写电脑上壳服务的地址与访问令牌（同局域网：192.168.x.x:8723；隧道/overlay：对应地址）。')
        .fontSize(13)
        .opacity(0.7)
      Text('地址').fontSize(13).margin({ top: 8 })
      TextInput({ text: this.urlText, placeholder: 'http://192.168.1.5:8723' })
        .id('input-url')
        .onChange((value: string) => {
          this.urlText = value;
        })
      Text('访问令牌（WUXING_SHELL_TOKEN）').fontSize(13).margin({ top: 4 })
      TextInput({
        text: this.tokenText,
        placeholder: this.tokenSaved ? '已保存（留空沿用）' : '粘贴访问令牌'
      })
        .id('input-token')
        .type(InputType.Password)
        .onChange((value: string) => {
          this.tokenText = value;
        })
      Button('连接')
        .id('btn-connect')
        .width('100%')
        .height(44)
        .onClick(() => {
          this.onConnect(this.urlText, this.tokenText);
        })
      if (this.status.length > 0) {
        Text(this.status)
          .fontSize(13)
          .fontColor('#A53F33')
          .id('config-status')
      }
      Text('令牌保存在系统安全存储（AssetStore），不以明文落盘。')
        .fontSize(12)
        .opacity(0.6)
    }
    .padding(24)
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
