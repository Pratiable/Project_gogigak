import json
from json.decoder import JSONDecodeError

from django.views         import View
from django.http.response import JsonResponse
from django.utils         import timezone
from django.db            import transaction

from users.models    import User, UserCoupon, Coupon
from orders.models   import CartItem, Order, OrderItem, OrderStatus, OrderItemStatus
from products.models import Product, Option, ProductOption
from utils           import login_decorator

class CartView(View):
    @login_decorator
    def get(self, request):
        try:
            signed_user = request.user
            items       = CartItem.objects.filter(user=signed_user).select_related(
                'product_options__option',
                'product_options__product'
                )
            cart_lists  = [
                    {
                    'cartItemId': item.id,
                    'thumbnail' : item.product_options.product.thumbnail,
                    'name'      : item.product_options.product.name,
                    'option'    : item.product_options.option.name,
                    'price'     : item.product_options.product.price,
                    'grams'     : item.product_options.product.grams,
                    'stock'     : item.product_options.product.stock,
                    'quantity'  : item.quantity if item.quantity <= item.product_options.product.stock else item.product_options.product.stock
                    } for item in items
            ]
            return JsonResponse({'cartItems':cart_lists}, status=200)
        
        except KeyError:
            return JsonResponse({'message':'KEY_ERROR'}, status=400)
        
        except User.DoesNotExist:
            return JsonResponse({'message':'INVALID_USER'}, status=400)
    
    @login_decorator
    def post(self, request):
        try:
            data           = json.loads(request.body)
            signed_user    = request.user
            quantity       = data['quantity']
            product_id     = data['productId']
            option_id      = data['optionId']
            
            if quantity < 1:
                return JsonResponse({'message':'INVALID_QUANTITY'}, status=400)

            if not Product.objects.filter(pk=data['productId']).exists():
                return JsonResponse({'message':'INVALID_PRODUCT'}, status=400)

            if not Option.objects.filter(pk=data['optionId']).exists():
                return JsonResponse({'message':'INVALID_OPTION'}, status=400)

            if not ProductOption.objects.filter(product_id=product_id, option_id=option_id).exists():
                return JsonResponse({'message':"INVALID_PRODUCTS_OPTION"}, status=400)
            
            product_option = ProductOption.objects.get(product=product_id, option=option_id)

            if quantity > product_option.product.stock:
                return JsonResponse({'message':'OUT_OF_STOCK'}, status=400)

            cart_item, is_created = CartItem.objects.get_or_create(
                user            = signed_user,
                product_options = product_option,
                defaults        = {'quantity': quantity}
            )
            
            if not is_created:
                cart_item.quantity += quantity

            if cart_item.quantity > product_option.product.stock:
                return JsonResponse({'message':'OUT_OF_STOCK'}, status=400)
                
            cart_item.save()
            return JsonResponse({'message':'SUCCESS'}, status=201)

        except KeyError:
            return JsonResponse({'message':'KEY_ERROR'}, status=400)

    @login_decorator
    def delete(self, request, cart_item):
        try:
            signed_user = request.user

            if cart_item == 0:
                items = CartItem.objects.filter(user=signed_user)
                items.delete()
                return JsonResponse({'message':'DELETE_SUCCESS'}, status=204)

            if not CartItem.objects.filter(pk=cart_item, user=signed_user).exists():
                return JsonResponse({'message':'NOT_FOUND'}, status=404)

            CartItem.objects.get(pk=cart_item, user=signed_user).delete()
            return JsonResponse({'message':'DELETE_SUCCESS'}, status=204)

        except KeyError:
            return JsonResponse({'message':'KEY_ERROR'}, status=200)
            
    @login_decorator
    def patch(self, request, cart_item):
        try:
            data          = json.loads(request.body)
            signed_user   = request.user
            item          = CartItem.objects.get(pk=cart_item)
            item.quantity = data['changeQuantity']

            if not CartItem.objects.filter(pk=cart_item, user=signed_user).exists():
                return JsonResponse({'message':'NOT_FOUND'}, status=404)

            product = item.product_options.product

            if item.quantity < 0:
                item.quantity = 0

            if item.quantity > product.stock:
                return JsonResponse({'message':'OUT_OF_STOCK'}, status=400)

            item.save()
            return JsonResponse({'message':'SUCCESS'}, status=200)

        except KeyError:
            return JsonResponse({'message':'KEY_ERROR'}, status=400)

class PurchaseView(View):
    @login_decorator
    def post(self, request):
        try:
            data              = json.loads(request.body)
            signed_user       = request.user
            cart_items        = CartItem.objects.filter(user=signed_user).select_related(
                'product_options__option',
                'product_options__product'
                )
            DELIVERY_VALUE    = {'default': 2500, 'free': 0}
            DELIVERY_STANDARD = 50000
            total_price       = 0
            delivery_fee      = DELIVERY_VALUE['default']
            coupon_id         = data.get('couponId', None)
            product_updates   = []

            if not cart_items.exists():
                return JsonResponse({"message":"NO_ITEMS_IN_CART"}, status=400)
            
            for cart_item in cart_items:
                if cart_item.quantity > cart_item.product_options.product.stock:
                    return JsonResponse({'message':'SOLD_OUT','soldOutProduct':cart_item.product_options.product.name}, status=400)

                product_update = cart_item.product_options.product
                product_update.sales += cart_item.quantity
                product_update.stock -= cart_item.quantity
                product_updates.append(product_update)

                total_price += (cart_item.quantity * cart_item.product_options.product.price)

            if not Order.objects.filter(user=signed_user).exists() or total_price > DELIVERY_STANDARD:
                delivery_fee = DELIVERY_VALUE['free']

            total_price += delivery_fee
            
            if coupon_id:
                if not UserCoupon.objects.filter(coupon=coupon_id, user=signed_user).exists():
                    return JsonResponse({'message':'INVALID_COUPON'}, status=400)

                UserCoupon.objects.filter(coupon=coupon_id, user=signed_user).first().delete()

                total_price -= Coupon.objects.get(pk=coupon_id).value
                total_price = 0 if total_price <= 0 else total_price

            with transaction.atomic():    
                order = Order.objects.create(
                    user          = signed_user,
                    delivery_date = timezone.localtime() + timezone.timedelta(days=2),
                    recipient     = signed_user.name,
                    phone_number  = signed_user.phone_number,
                    address       = signed_user.address,
                    coupon_id     = coupon_id,
                    delivery_fee  = delivery_fee,
                    status_id     = OrderStatus.PENDING,
                    total_price   = total_price,
                    point         = 0
                )

                OrderItem.objects.bulk_create(
                    [
                        OrderItem(
                            status_id         = OrderItemStatus.COMPLETED,
                            product_option_id = cart_item.product_options.id,
                            order             = order,
                            quantity          = cart_item.quantity
                        ) for cart_item in cart_items
                    ]
                )

                Product.objects.bulk_update(product_updates, fields=['stock'])
                Product.objects.bulk_update(product_updates, fields=['sales'])
                cart_items.delete()

            return JsonResponse({"message":"SUCCESS"}, status=201)

        except KeyError:
            return JsonResponse({"message":"KEY_ERROR"}, status=400)
        
        except JSONDecodeError:
            return JsonResponse({"message":"INVALID_JSON"}, status=400)