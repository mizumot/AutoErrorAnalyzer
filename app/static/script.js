function verify() {
  var textarea = document.getElementById('text');
  if (!textarea.value.trim()) {
      alert("You need to enter at least one word.");
      return false; // これを追加して、フォームが送信されないようにする。
  }
}

// fade in contents
$(document).ready(function(){
  $('body').fadeIn('slow');
});